"""Rate limiting (M6): slowapi + Redis, scoped per-tenant (the resolved Principal).

Wiring: the limiter is attached to the app in main.py (`app.state.limiter`, exception
handler, SlowAPIMiddleware). On protected routes we use `@limiter.limit(...)` with a
key_func that reads `request.state.tenant` — which a dependency (`set_tenant_on_state`)
sets BEFORE the slowapi wrapper runs its key_func (FastAPI resolves dependencies before
invoking the wrapped endpoint). Falls back to the client IP when no tenant is resolved
(local-dev / unauthenticated), so the limiter never fails open.

When REDIS_URL is unreachable or RATE_LIMIT_ENABLED is False, slowapi uses in-memory storage
(default) — so the stack still runs locally without Redis.
"""

from __future__ import annotations

from fastapi import Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import Principal, get_principal
from app.config import get_settings


def _storage_uri() -> str:
    s = get_settings()
    return s.redis_url if s.rate_limit_enabled else "memory://"


limiter = Limiter(key_func=get_remote_address, storage_uri=_storage_uri(), default_limits=[])


def tenant_key_func(request: Request) -> str:
    """Per-tenant bucket; fall back to client IP when no tenant is resolved."""
    tenant = getattr(request.state, "tenant", None)
    return f"tenant:{tenant}" if tenant else get_remote_address(request)


async def set_tenant_on_state(
    request: Request, principal: Principal | None = Depends(get_principal)
) -> None:
    """Stash the resolved tenant on request.state for the rate-limit key_func.

    FastAPI resolves this dependency (and get_principal) BEFORE invoking the slowapi-wrapped
    endpoint, so the key_func sees request.state.tenant when it runs.
    """
    request.state.tenant = principal.tenant_id if principal is not None else None
