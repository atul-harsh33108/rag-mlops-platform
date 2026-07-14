"""Postgres access (async). M1: tenant validation + corpus_version lookup.
M7 adds tenant API keys + the tenant_spend_monthly view over LiteLLM_SpendLogs."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine = None
_sessionmaker = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, future=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


async def get_session() -> AsyncSession:  # FastAPI dependency (used via Depends in M6+)
    sm = _sessionmaker
    async with sm() as session:
        yield session


@asynccontextmanager
async def session_context() -> AsyncIterator[AsyncSession]:
    """Use this outside of FastAPI Depends (e.g. in the /chat handler)."""
    sm = _sessionmaker
    async with sm() as session:
        yield session


async def tenant_exists(session: AsyncSession, tenant_id: str) -> bool:
    res = await session.execute(text("SELECT 1 FROM tenants WHERE id = :id"), {"id": tenant_id})
    return res.scalar() == 1


async def get_corpus_version(session: AsyncSession) -> int:
    res = await session.execute(text("SELECT corpus_version FROM corpus_state WHERE id = 1"))
    row = res.scalar()
    return int(row) if row is not None else get_settings().corpus_version


async def ensure_tenant(session: AsyncSession, tenant_id: str, name: str | None = None) -> None:
    await session.execute(
        text("INSERT INTO tenants (id, name) VALUES (:id, :name) ON CONFLICT (id) DO NOTHING"),
        {"id": tenant_id, "name": name or tenant_id},
    )
    await session.commit()
