"""Billing + metering (M7): plans, hard-budget caps, server-side usage metering, and the
Lago -> Stripe billing path.

Modules:
  - plans.PLAN    plan tier config (rate limits, monthly budget, models)
  - spend         enforce the per-tenant monthly hard budget cap (429 + upgrade prompt)
  - meter         record a usage_event (server-side truth; fixes LiteLLM stream under-count)
  - lago          Lago API client (customer / subscription / billable-metric event)

LiteLLM_SpendLogs -> tenant_spend_monthly (LiteLLM DB view) -> Lago billable metric -> Stripe
invoice is the metering spine; usage_events is the reconciliation source of truth on the app
side. See docs/decisions/0010-billing-lago-stripe.md + 0011-streaming-usage-reconciliation.md.
"""

from app.billing.plans import PLAN, Plan, get_plan

__all__ = ["PLAN", "Plan", "get_plan"]
