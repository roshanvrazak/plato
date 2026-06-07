from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from . import db, llm
from .auth import Tenant, require_tenant
from .observability import setup_observability, log


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_observability()
    await db.init_pool()
    llm.init_client()
    log.info("plato.startup")
    yield
    await llm.close_client()
    await db.close_pool()


app = FastAPI(title="plato-gateway", version="0.2.0", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(body: dict, tenant: Tenant = Depends(require_tenant)):
    if body.get("stream"):
        from fastapi.responses import StreamingResponse
        gen = llm.stream_chat_completion(tenant, body)
        return StreamingResponse(gen, media_type="text/event-stream")
    return await llm.chat_completion(tenant, body)