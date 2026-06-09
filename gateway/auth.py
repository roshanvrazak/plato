import hashlib
from dataclasses import dataclass
from decimal import Decimal
from fastapi import Header, HTTPException, status
from . import db
from decimal import Decimal

@dataclass
class Tenant:
    id: str
    name: str
    allowed_models: list[str]
    daily_token_budget: int
    daily_budget_pence: Decimal
    req_capacity: int
    req_refill_per_sec: Decimal
    token_capacity: int
    token_refill_per_sec: Decimal


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def require_tenant(x_api_key: str = Header(default="")) -> Tenant:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key")
    key_hash = hash_api_key(x_api_key)
    async with db.conn() as c:
        row = await c.fetchrow(
        """
        SELECT id, name, allowed_models, daily_token_budget, daily_budget_pence,
           req_capacity, req_refill_per_sec,
           token_capacity, token_refill_per_sec
        FROM tenants WHERE api_key_hash = $1
        """,
        key_hash,
      )
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    return Tenant(
        id=str(row["id"]),
        name=row["name"],
        allowed_models=list(row["allowed_models"]),
        daily_token_budget=row["daily_token_budget"],
        daily_budget_pence=row["daily_budget_pence"],
        req_capacity=row["req_capacity"],
        req_refill_per_sec=row["req_refill_per_sec"],
        token_capacity=row["token_capacity"],
        token_refill_per_sec=row["token_refill_per_sec"],
    )