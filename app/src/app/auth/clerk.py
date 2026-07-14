"""Clerk session-token verification (M6).

Clerk session tokens are RS256 JWTs. We verify the signature against the JWKS public key
(Clerk Frontend API `/.well-known/jwks.json`), check `exp`/`nbf`, validate `azp` against the
allowed origins, and extract the tenant from the v2 organization claim `o.id` (Clerk
Organizations = tenants; ADR 0006).

The JWT lib caches the JWKS signing key (PyJWKClient fetches + caches on first use, with a
short TTL via `cache_jwk_set=True`). For Keycloak (self-host, ADR 0006 fallback), point
CLERK_JWKS_URL at the realm's `/protocol/openid-connect/certs` — the same verify path works.
"""

from __future__ import annotations

from typing import Any

import jwt
from jwt import PyJWKClient
from pydantic import BaseModel

from app.config import get_settings
from app.observability import get_logger

_log = get_logger("auth.clerk")
_jwk_client: PyJWKClient | None = None


def _get_jwk_client() -> PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        s = get_settings()
        if not s.clerk_jwks_url:
            raise RuntimeError("CLERK_JWKS_URL unset — auth not configured")
        _jwk_client = PyJWKClient(s.clerk_jwks_url, cache_keys=True, lifespan=3600)
    return _jwk_client


class Principal(BaseModel):
    """The authenticated caller. tenant_id is the RLS scope (Qdrant group_id)."""

    tenant_id: str
    user_id: str | None = None
    org_role: str | None = None
    auth_method: str = "jwt"  # jwt | apikey
    key_id: int | None = None  # M7: API-key id for metering + per-key budget cap


def verify_token(token: str) -> Principal:
    """Verify a Clerk/Keycloak JWT and return the Principal (tenant from the org claim)."""
    s = get_settings()
    client = _get_jwk_client()
    signing_key = client.get_signing_key_from_jwt(token).key
    decoded: dict[str, Any] = jwt.decode(
        token,
        signing_key,
        algorithms=["RS256"],
        audience=s.jwt_audience,
        options={"verify_aud": False},  # Clerk session tokens don't always set `aud`
    )
    # azp (authorized party) must be one of our allowed origins.
    azp = decoded.get("azp")
    allowed = [p.strip() for p in s.clerk_authorized_parties.split(",") if p.strip()]
    if azp and allowed and azp not in allowed:
        raise PermissionError(f"unauthorized azp: {azp}")
    # v2 org claim: o.id. Fall back to `org_id` (older/custom template) or `tenant_id`.
    org = decoded.get("o") or {}
    tenant_id = (
        (org.get("id") if isinstance(org, dict) else None)
        or decoded.get("org_id")
        or decoded.get("tenant_id")
    )
    if not tenant_id:
        raise PermissionError("token has no tenant (organization) claim")
    return Principal(
        tenant_id=str(tenant_id),
        user_id=decoded.get("sub"),
        org_role=org.get("rol") if isinstance(org, dict) else None,
        auth_method="jwt",
    )
