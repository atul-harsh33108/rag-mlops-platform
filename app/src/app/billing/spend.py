"""Hard budget enforcement (M7). Before each generation we check the tenant's month-to-date
spend (from usage_events — the app's own metering) against the monthly budget. Over cap →
BudgetExceeded, which /chat maps to HTTP 429 with an upgrade prompt (NOT a 5xx; the client can
retry after upgrading).

The effective cap is the TIGHTER of the tenant budget and the presenting key's budget (a
sandbox key can be tighter than its tenant). Spend is read from usage_events so the cap reacts
to metering within the same request cycle (LiteLLM_SpendLogs lags by the proxy's flush cadence).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class BudgetExceeded(Exception):
    """Tenant/key is over its monthly budget. Maps to HTTP 429 + upgrade prompt."""

    def __init__(self, tenant_id: str, spent: float, cap: float, plan: str) -> None:
        self.tenant_id = tenant_id
        self.spent = spent
        self.cap = cap
        self.plan = plan
        super().__init__(
            f"tenant {tenant_id} over monthly budget: spent ${spent:.2f} / cap ${cap:.2f}"
        )


@dataclass
class TenantBilling:
    tenant_id: str
    plan: str
    monthly_budget_usd: float
    budget_hard_pct: int
    lago_customer_id: str | None
    lago_subscription_id: str | None
    stripe_customer_id: str | None


async def load_tenant_billing(session: AsyncSession, tenant_id: str) -> TenantBilling | None:
    row = (
        await session.execute(
            text(
                "SELECT id, plan, monthly_budget_usd, budget_hard_pct, "
                "       lago_customer_id, lago_subscription_id, stripe_customer_id "
                "FROM tenants WHERE id = :t"
            ),
            {"t": tenant_id},
        )
    ).first()
    if row is None:
        return None
    return TenantBilling(
        tenant_id=row.id,
        plan=row.plan,
        monthly_budget_usd=float(row.monthly_budget_usd),
        budget_hard_pct=int(row.budget_hard_pct),
        lago_customer_id=row.lago_customer_id,
        lago_subscription_id=row.lago_subscription_id,
        stripe_customer_id=row.stripe_customer_id,
    )


async def month_to_date_spend(session: AsyncSession, tenant_id: str) -> float:
    """Sum cost_usd for the tenant in the current UTC month from usage_events."""
    res = await session.execute(
        text(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM usage_events "
            "WHERE tenant_id = :t AND date_trunc('month', created_at) = date_trunc('month', now())"
        ),
        {"t": tenant_id},
    )
    return float(res.scalar() or 0.0)


async def key_month_to_date_spend(session: AsyncSession, key_id: int) -> float:
    res = await session.execute(
        text(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM usage_events "
            "WHERE key_id = :k AND date_trunc('month', created_at) = date_trunc('month', now())"
        ),
        {"k": key_id},
    )
    return float(res.scalar() or 0.0)


async def effective_cap(session: AsyncSession, billing: TenantBilling, key_id: int | None) -> float:
    """The tighter of the tenant cap and (if set) the presenting key's own budget."""
    tenant_cap = billing.monthly_budget_usd * (billing.budget_hard_pct / 100.0)
    if key_id is None:
        return tenant_cap
    key_budget = (
        await session.execute(
            text("SELECT monthly_budget_usd FROM tenant_api_keys WHERE id = :k"),
            {"k": key_id},
        )
    ).scalar()
    if key_budget is None or float(key_budget) <= 0:
        return tenant_cap
    return min(tenant_cap, float(key_budget))


async def assert_under_budget(
    session: AsyncSession, billing: TenantBilling, key_id: int | None
) -> float:
    """Raise BudgetExceeded if the tenant/key is over cap; return current spend otherwise."""
    cap = await effective_cap(session, billing, key_id)
    spent = await month_to_date_spend(session, billing.tenant_id)
    if key_id is not None:
        # The key's own spend is a subset of the tenant's, but the key cap may be tighter —
        # check it too so a sandbox key hits its own wall first.
        key_spent = await key_month_to_date_spend(session, key_id)
        if key_spent >= cap:
            raise BudgetExceeded(billing.tenant_id, key_spent, cap, billing.plan)
    if spent >= cap:
        raise BudgetExceeded(billing.tenant_id, spent, cap, billing.plan)
    return spent
