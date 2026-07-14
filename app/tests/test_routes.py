"""M7: the new admin + webhook routes are registered on the app (OpenAPI smoke)."""

from __future__ import annotations

import httpx
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_m7_routes_registered():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/openapi.json")
        assert r.status_code == 200
        paths = r.json()["paths"]
        expected = (
            "/admin/plan",
            "/admin/usage",
            "/admin/usage/forecast",
            "/webhooks/clerk",
            "/webhooks/stripe",
        )
        for path in expected:
            assert path in paths, f"missing route {path}"


@pytest.mark.asyncio
async def test_admin_requires_auth():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/admin/plan")
        # No Authorization header + auth_enabled default False -> get_principal returns None
        # -> require_principal raises 401. (When auth_enabled is True in prod the same path
        # 401s on a missing/invalid token.)
        assert r.status_code == 401
