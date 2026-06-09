"""Daily budget enforcement.

Window: Europe/London calendar day. All timestamps stored UTC; only the
window boundary uses the local timezone, because tenants think in
local-time days.

Concurrency note: this implementation has a check-then-write race window between
the budget read and the usage_log insert. Acceptable for low per-tenant concurrency.
The production upgrade is a per-tenant atomic counter in Redis, mirrored to
Postgres for audit. Same shape as the rate limiter's Lua-script pattern.
"""
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, time
from . import db
from .auth import Tenant
from .observability import meter
from opentelemetry import trace


LONDON = ZoneInfo("Europe/London")


@dataclass
class BudgetCheck:
    allowed: bool
    spent_today_pence: Decimal
    budget_pence: Decimal
    estimated_cost_pence: Decimal
    retry_after_seconds: int   # seconds until midnight London if rejected


tracer = trace.get_tracer("plato-gateway")

budget_rejection_counter = meter.create_counter(
    "plato.budget.rejections",
    description="Requests rejected due to budget exhaustion",
)

budget_spent_gauge = meter.create_up_down_counter(
    "plato.budget.spent_pence",
    description="Cumulative pence spent today, by tenant",
)


async def _spent_today_pence(tenant_id: str) -> Decimal:
    """Sum cost_pence for this tenant since today's midnight in Europe/London,
    converted to UTC for the query."""
    now_london = datetime.now(LONDON)
    start_of_day_london = datetime.combine(now_london.date(), time.min, tzinfo=LONDON)
    start_utc = start_of_day_london.astimezone(ZoneInfo("UTC"))

    async with db.conn() as c:
        spent = await c.fetchval(
            """
            SELECT COALESCE(SUM(cost_pence), 0)::NUMERIC
            FROM usage_log
            WHERE tenant_id = $1
              AND status_code < 400
              AND created_at >= $2
            """,
            tenant_id, start_utc,
        )
    return Decimal(spent or 0)


def _seconds_until_midnight_london() -> int:
    now = datetime.now(LONDON)
    tomorrow_midnight = datetime.combine(
        now.date() + timedelta(days=1), time.min, tzinfo=LONDON,
    )
    return int((tomorrow_midnight - now).total_seconds())


async def check_budget(tenant: Tenant, estimated_cost: Decimal) -> BudgetCheck:
    spent = await _spent_today_pence(tenant.id)
    would_be = spent + estimated_cost

    if would_be > tenant.daily_budget_pence:
        budget_rejection_counter.add(1, {"tenant": tenant.name})
        span = trace.get_current_span()
        if span is not None:
            span.set_attribute("plato.budget.rejected", True)
            span.set_attribute("plato.budget.spent_pence", float(spent))
            span.set_attribute("plato.budget.budget_pence", float(tenant.daily_budget_pence))
        return BudgetCheck(
            allowed=False,
            spent_today_pence=spent,
            budget_pence=tenant.daily_budget_pence,
            estimated_cost_pence=estimated_cost,
            retry_after_seconds=_seconds_until_midnight_london(),
        )

    return BudgetCheck(
        allowed=True,
        spent_today_pence=spent,
        budget_pence=tenant.daily_budget_pence,
        estimated_cost_pence=estimated_cost,
        retry_after_seconds=0,
    )