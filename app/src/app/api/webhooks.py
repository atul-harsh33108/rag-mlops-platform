"""Webhooks (M7): Clerk org -> tenant sync, and Stripe subscription -> plan/budget updates.

  POST /webhooks/clerk   organization.created/updated/deleted -> upsert/revoke tenant row
  POST /webhooks/stripe  customer.subscription.* / invoice.paid -> tenant plan + budget

Both verify request signatures (svix for Clerk, Stripe-Signature for Stripe). The signing
libraries are OPTIONAL — imported lazily inside the handlers so local dev without `svix`/
`stripe` installed still boots; a webhook arriving with no secret configured returns 503
(service misconfigured) rather than fail open.

Tenant <-> external id mapping:
  - Clerk: org.id == tenant.id (group_id). A new org -> a tenant row (plan=free).
  - Stripe: the Stripe Customer carries `metadata.tenant_id`; subscription.metadata.plan
    names the plan to activate. On cancel, the tenant drops back to free.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import text

from app.billing.plans import PLAN
from app.db import session_context
from app.observability import get_logger

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = get_logger("webhooks")


async def _set_tenant_plan(tenant_id: str, plan: str) -> None:
    plan = plan if plan in PLAN else "free"
    budget = PLAN[plan].monthly_budget_usd
    async with session_context() as session:
        await session.execute(
            text(
                "INSERT INTO tenants (id, name, plan, monthly_budget_usd) "
                "VALUES (:t, :t, :p, :b) "
                "ON CONFLICT (id) DO UPDATE SET plan = EXCLUDED.plan, "
                "  monthly_budget_usd = EXCLUDED.monthly_budget_usd, updated_at = now()"
            ),
            {"t": tenant_id, "p": plan, "b": budget},
        )
        await session.commit()


# --------------------------------------------------------------------------- Clerk
@router.post("/clerk")
async def clerk_webhook(
    request: Request,
    svix_id: str | None = Header(default=None),
    svix_timestamp: str | None = Header(default=None),
    svix_signature: str | None = Header(default=None),
) -> dict:
    from app.config import get_settings

    secret = get_settings().clerk_webhook_secret
    body = await request.body()
    if not secret:
        # No webhook secret configured — refuse rather than process unsigned events.
        raise HTTPException(status_code=503, detail="CLERK_WEBHOOK_SECRET not configured")
    try:
        from svix import Webhook  # type: ignore
    except ImportError:
        raise HTTPException(status_code=503, detail="svix not installed") from None

    wh = Webhook(secret)
    try:
        payload = wh.verify(
            body,
            {
                "svix-id": svix_id or "",
                "svix-timestamp": svix_timestamp or "",
                "svix-signature": svix_signature or "",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"invalid signature: {e}") from e

    event_type = payload.get("type", "")
    data = payload.get("data", {}) or {}
    org = data.get("object", {}) or {}
    org_id = org.get("id")
    if not org_id:
        return {"ok": True, "ignored": "no org id"}

    if event_type in ("organization.created", "organization.updated"):
        name = org.get("name") or org_id
        async with session_context() as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, plan) VALUES (:t, :n, 'free') "
                    "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, updated_at = now()"
                ),
                {"t": org_id, "n": name},
            )
            await session.commit()
        log.info("clerk_org_synced", org=org_id, name=name, event=event_type)
    elif event_type == "organization.deleted":
        # Don't hard-delete the tenant (keep billing/usage history); revoke all its keys.
        async with session_context() as session:
            await session.execute(
                text(
                    "UPDATE tenant_api_keys SET revoked_at = now() "
                    "WHERE tenant_id = :t AND revoked_at IS NULL"
                ),
                {"t": org_id},
            )
            await session.commit()
        log.info("clerk_org_deleted_keys_revoked", org=org_id)
    return {"ok": True, "type": event_type}


# --------------------------------------------------------------------------- Stripe
@router.post("/stripe")
async def stripe_webhook(request: Request) -> dict:
    import json

    from app.config import get_settings

    s = get_settings()
    if not s.stripe_webhook_secret or not s.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe not configured")
    try:
        import stripe  # type: ignore
    except ImportError:
        raise HTTPException(status_code=503, detail="stripe not installed") from None

    stripe.api_key = s.stripe_secret_key
    body = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(body, sig, s.stripe_webhook_secret)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid payload: {e}") from e
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(status_code=401, detail=f"invalid signature: {e}") from e

    etype = event["type"]
    obj = event.get("data", {}).get("object", {})

    if etype in ("customer.subscription.created", "customer.subscription.updated"):
        customer_id = obj.get("customer")
        plan = (obj.get("metadata") or {}).get("plan", "free")
        status = obj.get("status", "")
        # Map the tenant via the Stripe Customer's metadata.tenant_id (set at checkout).
        tenant_id = await _tenant_for_stripe_customer(customer_id)
        if tenant_id:
            effective = plan if status in ("active", "trialing", "past_due") else "free"
            await _set_tenant_plan(tenant_id, effective)
            log.info("stripe_subscription_updated", tenant=tenant_id, plan=effective, status=status)
    elif etype in ("customer.subscription.deleted", "customer.subscription.canceled"):
        customer_id = obj.get("customer")
        tenant_id = await _tenant_for_stripe_customer(customer_id)
        if tenant_id:
            await _set_tenant_plan(tenant_id, "free")
            log.info("stripe_subscription_canceled", tenant=tenant_id)
    elif etype == "invoice.paid":
        log.info("stripe_invoice_paid", invoice=obj.get("id"), amount=obj.get("amount_paid"))
    else:
        log.debug("stripe_event_ignored", type=etype)

    # Record the raw event for audit (best-effort).
    try:
        async with session_context() as session:
            await session.execute(
                text(
                    "INSERT INTO billing_ledger (tenant_id, event_type, payload, status) "
                    "VALUES (:t, :e, :p, 'received')"
                ),
                {
                    "t": "platform",
                    "e": etype,
                    "p": json.dumps({"event_id": event.get("id")}),
                },
            )
            await session.commit()
    except Exception as e:
        log.warning("stripe_ledger_failed", error=str(e))

    return {"ok": True, "type": etype}


async def _tenant_for_stripe_customer(customer_id: str | None) -> str | None:
    if not customer_id:
        return None
    async with session_context() as session:
        row = (
            await session.execute(
                text("SELECT id FROM tenants WHERE stripe_customer_id = :c"),
                {"c": customer_id},
            )
        ).scalar()
        if row:
            return str(row)
    # Fall back to Stripe customer metadata (set when we created the customer).
    try:
        import stripe  # type: ignore

        from app.config import get_settings

        stripe.api_key = get_settings().stripe_secret_key
        cust = stripe.Customer.retrieve(customer_id)
        tid = (cust.get("metadata") or {}).get("tenant_id")
        if tid:
            async with session_context() as session:
                await session.execute(
                    text(
                        "UPDATE tenants SET stripe_customer_id = :c, "
                        "updated_at = now() WHERE id = :t"
                    ),
                    {"c": customer_id, "t": tid},
                )
                await session.commit()
            return str(tid)
    except Exception as e:
        log.warning("stripe_customer_lookup_failed", customer=customer_id, error=str(e))
    return None
