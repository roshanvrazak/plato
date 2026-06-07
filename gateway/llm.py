import json
import time
import httpx
from fastapi import HTTPException, status
from .settings import settings
from .auth import Tenant
from . import db
from .observability import (
    tracer, input_tokens_counter, output_tokens_counter, ttft_histogram, log,
)


_client: httpx.AsyncClient | None = None


def init_client() -> None:
    global _client
    _client = httpx.AsyncClient(base_url=settings.litellm_url, timeout=120.0)


async def close_client() -> None:
    if _client:
        await _client.aclose()


def _check_model(tenant: Tenant, model: str) -> None:
    if model not in tenant.allowed_models:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Model '{model}' not permitted for tenant '{tenant.name}'",
        )


async def chat_completion(tenant: Tenant, body: dict) -> dict:
    model = body.get("model")
    _check_model(tenant, model)

    with tracer.start_as_current_span("llm.completion") as span:
        span.set_attribute("gen_ai.system", "ollama")
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("plato.tenant.id", tenant.id)
        span.set_attribute("plato.tenant.name", tenant.name)

        assert _client is not None
        response = await _client.post("/v1/chat/completions", json=body)

        if response.status_code >= 400:
            span.set_attribute("error", True)
            await _log_usage(tenant, model, 0, 0, response.status_code)
            raise HTTPException(response.status_code, response.text)

        data = response.json()
        usage = data.get("usage", {})
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)

        span.set_attribute("gen_ai.usage.input_tokens", in_tok)
        span.set_attribute("gen_ai.usage.output_tokens", out_tok)
        input_tokens_counter.add(in_tok, {"tenant": tenant.name, "model": model})
        output_tokens_counter.add(out_tok, {"tenant": tenant.name, "model": model})

        await _log_usage(tenant, model, in_tok, out_tok, 200)
        return data


async def stream_chat_completion(tenant: Tenant, body: dict):
    model = body.get("model")
    _check_model(tenant, model)
    body = {**body, "stream": True, "stream_options": {"include_usage": True}}

    span = tracer.start_span("llm.completion.stream")
    span.set_attribute("gen_ai.system", "ollama")
    span.set_attribute("gen_ai.request.model", model)
    span.set_attribute("plato.tenant.id", tenant.id)
    span.set_attribute("plato.tenant.name", tenant.name)
    span.set_attribute("plato.streaming", True)

    in_tok, out_tok = 0, 0
    first_token_time: float | None = None
    started = time.monotonic()

    try:
        assert _client is not None
        async with _client.stream("POST", "/v1/chat/completions", json=body) as response:
            if response.status_code >= 400:
                err_body = await response.aread()
                span.set_attribute("error", True)
                await _log_usage(tenant, model, 0, 0, response.status_code)
                yield f"data: {err_body.decode()}\n\n".encode()
                return

            async for chunk in response.aiter_bytes():
                if first_token_time is None:
                    first_token_time = time.monotonic()
                    ttft_ms = (first_token_time - started) * 1000
                    ttft_histogram.record(ttft_ms, {"tenant": tenant.name, "model": model})
                    span.set_attribute("plato.streaming.ttft_ms", ttft_ms)

                # Try to parse SSE events for usage (final chunk carries it)
                text = chunk.decode(errors="ignore")
                for line in text.splitlines():
                    if line.startswith("data: "):
                        payload = line[6:].strip()
                        if payload and payload != "[DONE]":
                            try:
                                evt = json.loads(payload)
                                usage = evt.get("usage")
                                if usage:
                                    in_tok = usage.get("prompt_tokens", in_tok)
                                    out_tok = usage.get("completion_tokens", out_tok)
                            except json.JSONDecodeError:
                                pass
                yield chunk

        span.set_attribute("gen_ai.usage.input_tokens", in_tok)
        span.set_attribute("gen_ai.usage.output_tokens", out_tok)
        input_tokens_counter.add(in_tok, {"tenant": tenant.name, "model": model})
        output_tokens_counter.add(out_tok, {"tenant": tenant.name, "model": model})
        await _log_usage(tenant, model, in_tok, out_tok, 200)

    except Exception as e:
        span.record_exception(e)
        span.set_attribute("error", True)
        log.error("plato.stream.error", error=str(e), tenant=tenant.name)
        raise
    finally:
        span.end()


async def _log_usage(
    tenant: Tenant, model: str, in_tok: int, out_tok: int, status_code: int
) -> None:
    async with db.conn() as c:
        await c.execute(
            "INSERT INTO usage_log (tenant_id, model, input_tokens, output_tokens, status_code) "
            "VALUES ($1, $2, $3, $4, $5)",
            tenant.id, model, in_tok, out_tok, status_code,
        )