"""Model pricing in pence per 1,000 tokens, input/output separately.

These rates are illustrative of mid-2026 published prices. In production this table
lives in Postgres and is updated without a deploy. Kept in code for portability of
the demo. Always Decimal — never float — for money.
"""
from decimal import Decimal
from typing import NamedTuple


class ModelPrice(NamedTuple):
    input_pence_per_1k: Decimal
    output_pence_per_1k: Decimal


PRICING: dict[str, ModelPrice] = {
    # Local models — zero cost
    "local-llama3": ModelPrice(Decimal("0.0"), Decimal("0.0")),
    "ollama/llama3.2:3b": ModelPrice(Decimal("0.0"), Decimal("0.0")),

    # Anthropic via direct API (pence per 1k tokens; GBP rough conversion of USD list prices)
    "anthropic/claude-3-5-haiku-20241022": ModelPrice(Decimal("0.08"), Decimal("0.40")),
    "anthropic/claude-3-5-sonnet-20241022": ModelPrice(Decimal("0.24"), Decimal("1.20")),

    # Bedrock
    "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0": ModelPrice(
        Decimal("0.24"), Decimal("1.20"),
    ),
}


def cost_pence(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Compute the cost of a completed call in pence. Returns 0 for unknown models
    rather than failing — pricing data freshness is a config concern, not a runtime one."""
    price = PRICING.get(model)
    if price is None:
        return Decimal("0")
    in_cost = price.input_pence_per_1k * Decimal(input_tokens) / Decimal("1000")
    out_cost = price.output_pence_per_1k * Decimal(output_tokens) / Decimal("1000")
    return (in_cost + out_cost).quantize(Decimal("0.0001"))


def estimate_cost_pence(model: str, est_input_tokens: int, max_output_tokens: int) -> Decimal:
    """Worst-case pre-flight estimate. Uses max_output_tokens as the upper bound."""
    return cost_pence(model, est_input_tokens, max_output_tokens)