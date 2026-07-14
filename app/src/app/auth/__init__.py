"""Auth package (M6): resolve the authenticated tenant from the request.

Resolution order (when AUTH_ENABLED):
  1. `Authorization: Bearer sk-...`  -> API key (hashed lookup in Postgres) -> tenant
  2. `Authorization: Bearer <jwt>`    -> Clerk/Keycloak JWT verify            -> tenant
  3. neither                          -> 401 (admin/keys paths) or fall back to body tenant (/chat)

When AUTH_ENABLED is False (local dev / CI evals), the dependency returns None and /chat
uses the body `tenant` (M1 mode). This keeps evals/seed working without Clerk configured.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException

from app.auth.apikey import verify_key
from app.auth.clerk import Principal, verify_token
from app.config import get_settings
from app.db import session_context

__all__ = ["Principal", "get_principal", "require_principal"]


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    return parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else None


async def get_principal(authorization: str | None = Header(default=None)) -> Principal | None:
    """Resolve the caller's Principal, or None when auth is disabled / no header.

    Uses its own short-lived DB session for the API-key lookup (the route handler opens a
    separate session for its own work — they don't share a transaction).
    """
    s = get_settings()
    token = _bearer(authorization)
    if not token:
        return None
    # API key path (sk-...). Must hit the DB. A presented-but-invalid/revoked key is a
    # hard 401 — never fall through to the body-tenant fallback (that would be fail-open).
    if token.startswith("sk-"):
        async with session_context() as session:
            principal = await verify_key(session, token)
        if principal is None:
            raise HTTPException(status_code=401, detail="invalid or revoked API key")
        return principal
    # JWT path (Clerk/Keycloak).
    if not s.clerk_jwks_url:
        # No JWKS configured — can't verify; treat as unauthenticated rather than fail open.
        raise HTTPException(status_code=401, detail="JWT presented but CLERK_JWKS_URL unset")
    try:
        return verify_token(token)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:  # malformed/expired token
        raise HTTPException(status_code=401, detail=f"invalid token: {e}") from e


async def require_principal(principal: Principal | None = Depends(get_principal)) -> Principal:
    """For admin/keys paths: a Principal is mandatory (no body-tenant fallback)."""
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return principal
