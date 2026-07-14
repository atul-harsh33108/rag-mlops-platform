"""Plan tiers (M7). The source of truth for per-plan rate limits, monthly budget, and model
access. The tenant's `plan` column (set by the Clerk/Stripe webhook) selects one of these.

A key inherits its tenant's plan; a key may carry a tighter `monthly_budget_usd` but the rate
limit always follows the tenant plan (so a single tenant can't mint many keys to evade limits).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    name: str
    rate_limit_per_minute: int
    monthly_budget_usd: float
    # Models this plan may route to (matched against the LiteLLM model_name). Empty = any.
    allowed_models: tuple[str, ...] = ()


PLAN: dict[str, Plan] = {
    "free": Plan(
        name="free",
        rate_limit_per_minute=20,
        monthly_budget_usd=50.00,
        allowed_models=("qwen3:14b",),
    ),
    "pro": Plan(
        name="pro",
        rate_limit_per_minute=120,
        monthly_budget_usd=500.00,
        allowed_models=("qwen3:14b", "judge"),
    ),
    "enterprise": Plan(
        name="enterprise",
        rate_limit_per_minute=600,
        monthly_budget_usd=5000.00,
        allowed_models=(),  # any model
    ),
}

DEFAULT_PLAN = "free"


def get_plan(name: str | None) -> Plan:
    """Return the plan, falling back to free for unknown/missing."""
    if not name or name not in PLAN:
        return PLAN[DEFAULT_PLAN]
    return PLAN[name]
