"""Admin / self-serve billing API (M7). All paths require a Principal (tenant-scoped: a
tenant admin sees their OWN tenant's usage/budget, never another tenant's).

  GET /admin/plan            -> plan + budget + spend + cap + rate limit
  GET /admin/usage           -> this month: request_count, tokens, cost_usd, by_model:[...]
  GET /admin/usage/forecast  -> spent + projected month-end + days elapsed/in-month
  GET /admin/keys            -> (delegated to /keys; listed here for the admin UI manifest)

Cross-tenant platform-admin views (all tenants, revenue) are deferred — out of M7 scope and
need a separate platform-admin role (documented in docs/runbooks/saas.md).
"""

from __future__ import annotations

import calendar
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, require_principal
from app.billing.plans import get_plan
from app.billing.spend import load_tenant_billing, month_to_date_spend
from app.db import get_session

router = APIRouter(prefix="/admin", tags=["admin"])


def _utcnow() -> datetime:
    return datetime.now(tz=datetime.UTC)


def _month_progress() -> tuple[int, int, int]:
    """Return (days_elapsed_inclusive, days_in_month, day_of_month) for the UTC current month."""
    now = _utcnow()
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    return now.day, days_in_month, now.day


@router.get("/plan")
async def plan_summary(
    principal: Principal = Depends(require_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    billing = await load_tenant_billing(session, principal.tenant_id)
    spent = await month_to_date_spend(session, principal.tenant_id)
    plan = get_plan(billing.plan if billing else None)
    budget = billing.monthly_budget_usd if billing else plan.monthly_budget_usd
    cap = budget * ((billing.budget_hard_pct if billing else 100) / 100.0)
    return {
        "tenant_id": principal.tenant_id,
        "plan": plan.name,
        "monthly_budget_usd": round(budget, 2),
        "cap_usd": round(cap, 2),
        "spent_usd": round(spent, 2),
        "remaining_usd": round(max(0.0, cap - spent), 2),
        "rate_limit_per_minute": plan.rate_limit_per_minute,
    }


@router.get("/usage")
async def usage(
    principal: Principal = Depends(require_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    tenant = principal.tenant_id
    row = (
        await session.execute(
            text(
                "SELECT request_count, prompt_tokens, completion_tokens, total_tokens, "
                "       cost_usd, estimated_frac "
                "FROM tenant_usage_monthly "
                "WHERE tenant_id = :t AND usage_month = date_trunc('month', now())"
            ),
            {"t": tenant},
        )
    ).first()
    if row is None:
        return {
            "tenant_id": tenant,
            "month": _utcnow().strftime("%Y-%m"),
            "request_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "estimated_frac": 0.0,
            "by_model": [],
        }
    by_model = (
        await session.execute(
            text(
                "SELECT model, COUNT(*) AS request_count, SUM(total_tokens) AS total_tokens, "
                "       SUM(cost_usd) AS cost_usd "
                "FROM usage_events "
                "WHERE tenant_id = :t "
                "  AND date_trunc('month', created_at) = date_trunc('month', now()) "
                "GROUP BY model ORDER BY cost_usd DESC"
            ),
            {"t": tenant},
        )
    ).all()
    return {
        "tenant_id": tenant,
        "month": _utcnow().strftime("%Y-%m"),
        "request_count": int(row.request_count),
        "prompt_tokens": int(row.prompt_tokens),
        "completion_tokens": int(row.completion_tokens),
        "total_tokens": int(row.total_tokens),
        "cost_usd": round(float(row.cost_usd), 4),
        "estimated_frac": round(float(row.estimated_frac or 0), 3),
        "by_model": [
            {
                "model": r.model,
                "request_count": int(r.request_count),
                "total_tokens": int(r.total_tokens),
                "cost_usd": round(float(r.cost_usd), 4),
            }
            for r in by_model
        ],
    }


@router.get("/usage/forecast")
async def forecast(
    principal: Principal = Depends(require_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Linear month-end spend forecast: spent / days_elapsed * days_in_month."""
    spent = await month_to_date_spend(session, principal.tenant_id)
    days_elapsed, days_in_month, day = _month_progress()
    projected = (spent / days_elapsed) * days_in_month if days_elapsed else 0.0
    return {
        "tenant_id": principal.tenant_id,
        "spent_usd": round(spent, 2),
        "projected_month_end_usd": round(projected, 2),
        "days_elapsed": days_elapsed,
        "days_in_month": days_in_month,
    }
