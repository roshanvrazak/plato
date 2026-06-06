import uuid
import hashlib
from dataclasses import dataclass
from fastapi import Header, HTTPException, status
from . import db


@dataclass
class Tenant:
    id: uuid.UUID
    name: str
    allowed_models: list[str]
    daily_token_budget: int


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def require_tenant(x_api_key: str = Header(default="")) -> Tenant:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key")
    key_hash = hash_api_key(x_api_key)
    async with db.conn() as c:
        row = await c.fetchrow(
            "SELECT id, name, allowed_models, daily_token_budget "
            "FROM tenants WHERE api_key_hash = $1",
            key_hash,
        )
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    return Tenant(
        id=row["id"],
        name=row["name"],
        allowed_models=list(row["allowed_models"]),
        daily_token_budget=row["daily_token_budget"],
    )