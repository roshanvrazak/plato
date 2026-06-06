import httpx
from fastapi import HTTPException, status
from .settings import settings
from .auth import Tenant
from . import db


_client: httpx.AsyncClient | None = None


def init_client() -> None:
    global _client
    _client = httpx.AsyncClient(base_url=settings.litellm_url, timeout=60.0)


async def close_client() -> None:
    if _client:
        await _client.aclose()


async def _tokens_used_today(tenant: Tenant) -> int:
    async with db.conn() as c:
        row = await c.fetchrow(
            "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS total "
            "FROM usage_log "
            "WHERE tenant_id = $1 AND created_at >= NOW() - INTERVAL '1 day'",
            tenant.id,
        )
    return int(row["total"])


async def chat_completion(tenant: Tenant, body: dict) -> dict:
    model = body.get("model")
    if model not in tenant.allowed_models:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Model '{model}' not permitted for tenant '{tenant.name}'",
        )

    used = await _tokens_used_today(tenant)
    if used >= tenant.daily_token_budget:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Daily token budget of {tenant.daily_token_budget} exhausted",
        )

    assert _client is not None
    response = await _client.post("/v1/chat/completions", json=body)

    if response.status_code >= 400:
        # Log the failure but still return upstream's error to the caller
        await _log_usage(tenant, model, 0, 0, response.status_code)
        raise HTTPException(response.status_code, response.text)

    data = response.json()
    usage = data.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)
    await _log_usage(tenant, model, input_tokens, output_tokens, 200)
    return data


async def _log_usage(
    tenant: Tenant, model: str, in_tok: int, out_tok: int, status_code: int
) -> None:
    async with db.conn() as c:
        await c.execute(
            "INSERT INTO usage_log (tenant_id, model, input_tokens, output_tokens, status_code) "
            "VALUES ($1, $2, $3, $4, $5)",
            tenant.id, model, in_tok, out_tok, status_code,
        )