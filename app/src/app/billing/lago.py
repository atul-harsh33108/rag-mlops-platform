"""Lago API client (M7). Manages the billing lifecycle: create a customer + subscription in
Lago when a tenant upgrades, and record each sync in billing_ledger for reconciliation.

LiteLLM's `lago` success_callback handles the *metering* — it reports each LLM call's spend as
a billable-metric event to Lago (config in docker/litellm/config.eks.yaml). This module handles
the *lifecycle*: turning a tenant into a Lago customer with an active subscription on the
matching plan. Lago then invoices via Stripe.

API pinned to Lago's REST shape (v1). All calls are optional — if LAGO_API_BASE/KEY are unset,
methods no-op and return None, so local dev without Lago still works.
"""

from __future__ import annotations

import json

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.observability import get_logger

_log = get_logger("billing.lago")

# Pin the Lago API contract we target. Bump + retest when upgrading.
LAGO_API_VERSION = "2024-09-01"

# Our plan names -> Lago plan codes (created in Lago out-of-band; see docs/runbooks/saas.md).
PLAN_TO_LAGO_CODE: dict[str, str] = {
    "free": "free",
    "pro": "pro",
    "enterprise": "enterprise",
}


def _enabled() -> bool:
    s = get_settings()
    return bool(s.lago_api_base and s.lago_api_key)


def _client() -> httpx.AsyncClient:
    s = get_settings()
    headers = {
        "Authorization": f"Bearer {s.lago_api_key}",
        "Content-Type": "application/json",
        "X-Lago-Version": LAGO_API_VERSION,
    }
    return httpx.AsyncClient(base_url=s.lago_api_base, headers=headers, timeout=30.0)


async def _ledger(
    session: AsyncSession,
    tenant_id: str,
    event_type: str,
    lago_id: str | None,
    payload: dict,
    status: str,
) -> None:
    await session.execute(
        text(
            "INSERT INTO billing_ledger (tenant_id, event_type, lago_id, payload, status) "
            "VALUES (:t, :e, :l, :p, :s)"
        ),
        {"t": tenant_id, "e": event_type, "l": lago_id, "p": json.dumps(payload), "s": status},
    )
    await session.commit()


async def ensure_customer(session: AsyncSession, tenant_id: str, name: str) -> str | None:
    """Create the Lago customer if the tenant doesn't have one yet; persist the id."""
    if not _enabled():
        return None
    # Read existing first (idempotent — webhook may fire more than once).
    existing = (
        await session.execute(
            text("SELECT lago_customer_id FROM tenants WHERE id = :t"), {"t": tenant_id}
        )
    ).scalar()
    if existing:
        return existing
    payload = {"customer": {"external_id": tenant_id, "name": name}}
    try:
        async with _client() as c:
            resp = await c.post("/customers", json=payload)
            resp.raise_for_status()
            lago_id = resp.json()["customer"]["lago_id"]
    except Exception as e:  # network / API error — log + ledger, don't break the upgrade flow
        _log.warning("lago ensure_customer failed", tenant=tenant_id, error=str(e))
        await _ledger(session, tenant_id, "customer_created", None, payload, "failed")
        return None
    await session.execute(
        text("UPDATE tenants SET lago_customer_id = :l, updated_at = now() WHERE id = :t"),
        {"l": lago_id, "t": tenant_id},
    )
    await session.commit()
    await _ledger(session, tenant_id, "customer_created", lago_id, payload, "sent")
    return lago_id


async def create_subscription(session: AsyncSession, tenant_id: str, plan: str) -> str | None:
    """Activate a Lago subscription for the tenant on the given plan code."""
    if not _enabled():
        return None
    code = PLAN_TO_LAGO_CODE.get(plan, PLAN_TO_LAGO_CODE["free"])
    customer_id = (
        await session.execute(
            text("SELECT lago_customer_id FROM tenants WHERE id = :t"), {"t": tenant_id}
        )
    ).scalar()
    if not customer_id:
        _log.warning("create_subscription: no lago_customer_id", tenant=tenant_id)
        return None
    payload = {
        "subscription": {
            "external_customer_id": tenant_id,
            "plan_code": code,
            "status": "active",
        }
    }
    try:
        async with _client() as c:
            resp = await c.post("/subscriptions", json=payload)
            resp.raise_for_status()
            sub_id = resp.json()["subscription"]["lago_id"]
    except Exception as e:
        _log.warning("lago create_subscription failed", tenant=tenant_id, error=str(e))
        await _ledger(session, tenant_id, "subscription", None, payload, "failed")
        return None
    await session.execute(
        text("UPDATE tenants SET lago_subscription_id = :l, updated_at = now() WHERE id = :t"),
        {"l": sub_id, "t": tenant_id},
    )
    await session.commit()
    await _ledger(session, tenant_id, "subscription", sub_id, payload, "sent")
    return sub_id
