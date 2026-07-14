"""Health + readiness probes."""

from __future__ import annotations

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.cache.semantic_cache import SemanticCache
from app.config import get_settings
from app.db import get_engine

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness — process is up."""
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, object]:
    """Readiness — dependencies reachable. Used by k8s readinessProbe (M4)."""
    s = get_settings()
    deps: dict[str, object] = {}

    # Qdrant
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"http://{s.qdrant_host}:{s.qdrant_port}/healthz")
            deps["qdrant"] = "ok" if r.status_code == 200 else f"bad:{r.status_code}"
    except Exception as e:
        deps["qdrant"] = f"down:{e}"

    # TEI
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"http://{s.tei_host}:{s.tei_port}/health")
            deps["tei"] = "ok" if r.status_code == 200 else f"bad:{r.status_code}"
    except Exception as e:
        deps["tei"] = f"down:{e}"

    # Postgres
    try:
        eng = get_engine()
        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))
            deps["postgres"] = "ok"
    except Exception as e:
        deps["postgres"] = f"down:{e}"

    # Redis
    deps["redis"] = "ok" if await SemanticCache().ping() else "down"

    ok = all(v == "ok" for v in deps.values())
    return {"status": "ok" if ok else "degraded", "deps": deps}
