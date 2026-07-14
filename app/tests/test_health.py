"""Smoke test the FastAPI app boots and /health responds. Uses httpx ASGI transport so
no real dependencies are required (the /ready probe would need them, so we only test /health).
"""

from __future__ import annotations

import httpx
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_health():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_openapi():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/openapi.json")
        assert r.status_code == 200
        paths = r.json()["paths"]
        assert "/chat" in paths
        assert "/ingest" in paths
        assert "/health" in paths
