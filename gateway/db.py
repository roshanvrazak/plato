import asyncpg
from contextlib import asynccontextmanager
from .settings import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        settings.database_url, min_size=2, max_size=10
    )


async def close_pool() -> None:
    if _pool:
        await _pool.close()


def pool() -> asyncpg.Pool:
    assert _pool is not None, "DB pool not initialised"
    return _pool


@asynccontextmanager
async def conn():
    async with pool().acquire() as c:
        yield c