from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from . import db, llm
from .auth import Tenant, require_tenant


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    llm.init_client()
    yield
    await llm.close_client()
    await db.close_pool()


app = FastAPI(title="plato-gateway", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(body: dict, tenant: Tenant = Depends(require_tenant)):
    return await llm.chat_completion(tenant, body)