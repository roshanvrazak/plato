from dataclasses import dataclass
from typing import Optional
import redis.asyncio as redis
from opentelemetry import trace
from .settings import settings
from .auth import Tenant
from .observability import meter

# ----------------------------------------------------------------------------
# Lua script — atomic token bucket
# KEYS[1] : bucket key
# ARGV[1] : capacity
# ARGV[2] : refill rate per second
# ARGV[3] : now (epoch milliseconds, integer)
# ARGV[4] : requested tokens
# Returns: { allowed (0|1), tokens_remaining, retry_after_ms }
# ----------------------------------------------------------------------------
LUA_TOKEN_BUCKET = """
local capacity      = tonumber(ARGV[1])
local refill_rate   = tonumber(ARGV[2])
local now_ms        = tonumber(ARGV[3])
local requested     = tonumber(ARGV[4])

local state    = redis.call('HMGET', KEYS[1], 'tokens', 'last_refill_ms')
local tokens   = tonumber(state[1])
local last_ms  = tonumber(state[2])

if tokens == nil then
  tokens  = capacity
  last_ms = now_ms
end

-- refill based on elapsed time
local elapsed_ms = math.max(0, now_ms - last_ms)
local refill     = (elapsed_ms / 1000.0) * refill_rate
tokens           = math.min(capacity, tokens + refill)
last_ms          = now_ms

local allowed = 0
local retry_after_ms = 0
if tokens >= requested then
  tokens  = tokens - requested
  allowed = 1
else
  local deficit = requested - tokens
  retry_after_ms = math.ceil((deficit / refill_rate) * 1000)
end

redis.call('HMSET', KEYS[1], 'tokens', tokens, 'last_refill_ms', last_ms)
-- 1-hour idle expiry so cold tenants don't accumulate keys forever
redis.call('PEXPIRE', KEYS[1], 3600000)

return { allowed, tostring(tokens), retry_after_ms }
"""


@dataclass
class LimitResult:
    allowed: bool
    bucket: str               # "requests" or "tokens"
    tokens_remaining: float
    retry_after_seconds: float


tracer = trace.get_tracer("plato-gateway")

rejection_counter = meter.create_counter(
    "plato.ratelimit.rejections",
    description="Rate-limit rejections by bucket",
)


class RateLimiter:
    def __init__(self) -> None:
        self._redis: Optional[redis.Redis] = None
        self._script_sha: Optional[str] = None

    async def init(self) -> None:
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        self._script_sha = await self._redis.script_load(LUA_TOKEN_BUCKET)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    async def _check_bucket(
        self,
        key: str,
        capacity: int,
        refill_per_sec: float,
        requested: int,
    ) -> tuple[bool, float, float]:
        assert self._redis is not None and self._script_sha is not None
        import time
        now_ms = int(time.time() * 1000)
        result = await self._redis.evalsha(
            self._script_sha, 1, key,
            capacity, refill_per_sec, now_ms, requested,
        )
        allowed = bool(int(result[0]))
        tokens_remaining = float(result[1])
        retry_after_seconds = float(result[2]) / 1000.0
        return allowed, tokens_remaining, retry_after_seconds

    async def check(self, tenant: Tenant, est_tokens: int) -> LimitResult:
        # Request bucket first — cheap rejection for crude abuse
        ok_req, rem_req, retry_req = await self._check_bucket(
            f"rl:req:{tenant.id}",
            tenant.req_capacity,
            float(tenant.req_refill_per_sec),
            1,
        )

        if not ok_req:
            self._record_rejection(tenant, "requests", retry_req)
            return LimitResult(
                allowed=False, bucket="requests",
                tokens_remaining=rem_req, retry_after_seconds=retry_req,
            )

        # Token bucket — the real budget
        ok_tok, rem_tok, retry_tok = await self._check_bucket(
            f"rl:tok:{tenant.id}",
            tenant.token_capacity,
            float(tenant.token_refill_per_sec),
            est_tokens,
        )

        if not ok_tok:
            self._record_rejection(tenant, "tokens", retry_tok)
            # Note: we already consumed 1 from request bucket above.
            # Acceptable trade-off; the alternative (refund) makes the script much hairier.
            return LimitResult(
                allowed=False, bucket="tokens",
                tokens_remaining=rem_tok, retry_after_seconds=retry_tok,
            )

        return LimitResult(
            allowed=True, bucket="tokens",
            tokens_remaining=rem_tok, retry_after_seconds=0.0,
        )

    def _record_rejection(self, tenant: Tenant, bucket: str, retry_after_seconds: float) -> None:
        rejection_counter.add(1, {"tenant": tenant.name, "bucket": bucket})
        span = trace.get_current_span()
        if span is not None:
            span.set_attribute("plato.ratelimit.rejected", True)
            span.set_attribute("plato.ratelimit.bucket", bucket)
            span.set_attribute("plato.ratelimit.retry_after_seconds", retry_after_seconds)


limiter = RateLimiter()