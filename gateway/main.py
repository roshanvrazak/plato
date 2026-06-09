from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from . import db, llm
from .auth import Tenant, require_tenant
from .rate_limit import limiter
from .observability import setup_observability, log
from decimal import Decimal
from .budget import check_budget
from .pricing import estimate_cost_pence




@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_observability()
    await db.init_pool()
    await limiter.init()
    llm.init_client()
    log.info("plato.startup")
    yield
    await llm.close_client()
    await limiter.close()
    await db.close_pool()


app = FastAPI(title="plato-gateway", version="0.3.0", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)


def _estimate_tokens(body: dict) -> int:
    """Cheap pre-flight estimate: sum message content length / 4 (chars-per-token rule of thumb)
    plus requested max_tokens. Conservative — we'd rather slightly over-estimate."""
    msg_chars = sum(len(m.get("content", "")) for m in body.get("messages", []))
    input_estimate = max(1, msg_chars // 4)
    max_out = body.get("max_tokens", 512)
    return input_estimate + max_out


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(body: dict, tenant: Tenant = Depends(require_tenant)):
    est_tokens = _estimate_tokens(body)
    result = await limiter.check(tenant, est_tokens)

    if not result.allowed:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(int(result.retry_after_seconds) + 1)},
            content={
                "error": {
                    "type": "rate_limit_exceeded",
                    "bucket": result.bucket,
                    "tokens_remaining": result.tokens_remaining,
                    "retry_after_seconds": round(result.retry_after_seconds, 2),
                }
            },
        )



    # Budget check
    model = body.get("model", "")
    msg_chars = sum(len(m.get("content", "")) for m in body.get("messages", []))
    est_input_tokens = max(1, msg_chars // 4)
    max_out_tokens = body.get("max_tokens", 512)
    est_cost = estimate_cost_pence(model, est_input_tokens, max_out_tokens)

    bc = await check_budget(tenant, est_cost)
    if not bc.allowed:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(bc.retry_after_seconds)},
            content={
                "error": {
                    "type": "daily_budget_exceeded",
                    "reason": "budget_exhausted",
                    "spent_today_pence": float(bc.spent_today_pence),
                    "budget_pence": float(bc.budget_pence),
                    "estimated_cost_pence": float(bc.estimated_cost_pence),
                    "retry_after_seconds": bc.retry_after_seconds,
                }
            },
        )

    if body.get("stream"):
        from fastapi.responses import StreamingResponse
        gen = llm.stream_chat_completion(tenant, body)
        return StreamingResponse(gen, media_type="text/event-stream")
    return await llm.chat_completion(tenant, body)