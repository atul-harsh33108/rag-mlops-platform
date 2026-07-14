"""API-key authentication (M6): hashed per-tenant keys for programmatic access.

Keys are `sk-<tenant>-<random>`; we store only the SHA-256 hash (never the plaintext after
issue). Lookup is by hash; we return the tenant (RLS scope) + key id (for rate-limit/billing
attribution). M7 adds plan-scoped keys + spend caps; M6 keeps a single tier.

Schema (`docker/postgres/init/03_api_keys.sql`):
  tenant_api_keys(id, tenant_id, key_hash UNIQUE, label, created_at, last_used_at, revoked_at)
"""

from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.clerk import Principal


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate_key(tenant_id: str) -> str:
    """Return a freshly minted plaintext key (shown ONCE to the caller)."""
    rand = secrets.token_urlsafe(32)
    return f"sk-{tenant_id}-{rand}"


async def create_key(session: AsyncSession, tenant_id: str, label: str) -> tuple[str, int]:
    """Create a key for a tenant; return (plaintext, key_id). Plaintext is shown once."""
    plaintext = generate_key(tenant_id)
    h = hash_key(plaintext)
    res = await session.execute(
        text(
            "INSERT INTO tenant_api_keys (tenant_id, key_hash, label) "
            "VALUES (:t, :h, :l) RETURNING id"
        ),
        {"t": tenant_id, "h": h, "l": label},
    )
    key_id = res.scalar_one()
    await session.commit()
    return plaintext, int(key_id)


async def verify_key(session: AsyncSession, plaintext: str) -> Principal | None:
    """Look up a key by hash; return Principal or None. Bumps last_used_at on success."""
    if not plaintext.startswith("sk-"):
        return None
    h = hash_key(plaintext)
    res = await session.execute(
        text(
            "UPDATE tenant_api_keys SET last_used_at = now() "
            "WHERE key_hash = :h AND revoked_at IS NULL "
            "RETURNING id, tenant_id"
        ),
        {"h": h},
    )
    row = res.first()
    if row is None:
        return None
    return Principal(tenant_id=row.tenant_id, auth_method="apikey")


async def list_keys(session: AsyncSession, tenant_id: str) -> list[dict]:
    res = await session.execute(
        text(
            "SELECT id, tenant_id, label, created_at, last_used_at, revoked_at "
            "FROM tenant_api_keys WHERE tenant_id = :t ORDER BY created_at DESC"
        ),
        {"t": tenant_id},
    )
    return [dict(r._mapping) for r in res.all()]


async def revoke_key(session: AsyncSession, tenant_id: str, key_id: int) -> bool:
    res = await session.execute(
        text(
            "UPDATE tenant_api_keys SET revoked_at = now() "
            "WHERE id = :id AND tenant_id = :t AND revoked_at IS NULL"
        ),
        {"id": key_id, "t": tenant_id},
    )
    await session.commit()
    return res.rowcount > 0
