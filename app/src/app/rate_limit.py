"""Rate limiting (M6/M7): slowapi + Redis, scoped per-tenant, with per-PLAN limits.

Wiring: the limiter is attached to the app in main.py (`app.state.limiter`, exception
handler, SlowAPIMiddleware). On protected routes we use `@limiter.limit(plan_rate_limit,
key_func=tenant_key_func)` — `plan_rate_limit` is a callable that reads `request.state.plan`
(which `set_tenant_on_state` sets BEFORE the slowapi wrapper runs its limit/key funcs —
FastAPI resolves dependencies before invoking the wrapped endpoint) and returns the plan's
rate string (e.g. `"120/minute"` for pro). Falls back to the client IP when no tenant is
resolved (local-dev / unauthenticated), so the limiter never fails open.

When REDIS_URL is unreachable or RATE_LIMIT_ENABLED is False, slowapi uses in-memory storage
(default) — so the stack still runs locally without Redis.

Plan lookup is cached per-tenant in-process (30s TTL) so the sync limit callable never does
I/O. The plan follows the TENANT, not the key, so a tenant can't mint many keys to evade the
limit (ADR 0010).
"""

from __future__ import annotations

import time

from fastapi import Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import Principal, get_principal
from app.billing.plans import get_plan
from app.config import get_settings
from app.db import session_context

_PLAN_CACHE: dict[str, tuple[str, float]] = {}
_PLAN_TTL = 30.0


def _storage_uri() -> str:
    s = get_settings()
    return s.redis_url if s.rate_limit_enabled else "memory://"


limiter = Limiter(key_func=get_remote_address, storage_uri=_storage_uri(), default_limits=[])


async def _load_plan(tenant_id: str) -> str:
    """Cached tenant plan lookup (30s TTL). Falls back to the default plan on any miss."""
    now = time.monotonic()
    cached = _PLAN_CACHE.get(tenant_id)
    if cached and cached[1] > now:
        return cached[0]
    plan = get_plan(None).name  # default
    try:
        async with session_context() as session:
            from sqlalchemy import text

            row = (
                await session.execute(
                    text("SELECT plan FROM tenants WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar()
            if row:
                plan = str(row)
    except Exception:
        pass  # DB down in local dev — keep the default; don't break /chat
    _PLAN_CACHE[tenant_id] = (plan, now + _PLAN_TTL)
    return plan


def tenant_key_func(request: Request) -> str:
    """Per-tenant bucket; fall back to client IP when no tenant is resolved."""
    tenant = getattr(request.state, "tenant", None)
    return f"tenant:{tenant}" if tenant else get_remote_address(request)


def plan_rate_limit(request: Request) -> str:
    """Dynamic per-plan limit string. Reads request.state.plan set by set_tenant_on_state."""
    plan_name = getattr(request.state, "plan", None)
    plan = get_plan(plan_name)
    return f"{plan.rate_limit_per_minute}/minute"


async def set_tenant_on_state(
    request: Request, principal: Principal | None = Depends(get_principal)
) -> None:
    """Stash the resolved tenant + plan on request.state for the rate-limit funcs.

    FastAPI resolves this dependency (and get_principal) BEFORE invoking the slowapi-wrapped
    endpoint, so the funcs see request.state.tenant/plan when they run.
    """
    tenant = principal.tenant_id if principal is not None else None
    request.state.tenant = tenant
    request.state.plan = await _load_plan(tenant) if tenant else None
