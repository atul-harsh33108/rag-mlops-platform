"""Tenant RLS is the security-critical boundary. These tests assert it can never be
absent from a Qdrant search payload — a missing group_id filter is a security bug
(this is the CI guard the plan calls for in M2/M6).
"""

from __future__ import annotations

import pytest
from qdrant_client.http import models

from app.qdrant.filter_builder import TenantFilterBuilder, assert_filter_has_tenant


def test_build_filter_includes_tenant():
    f = TenantFilterBuilder("acme").build()
    assert isinstance(f, models.Filter)
    assert_filter_has_tenant(f, "acme")


def test_build_filter_with_extras_still_scoped_to_tenant():
    extra = [
        models.FieldCondition(key="source", match=models.MatchValue(value="FAQ: Password reset"))
    ]
    f = TenantFilterBuilder("acme").build(extra=extra)
    assert_filter_has_tenant(f, "acme")
    # extra condition is present alongside the tenant condition
    keys = {c.key for c in f.must}
    assert "source" in keys and "group_id" in keys


def test_empty_tenant_raises():
    with pytest.raises(ValueError):
        TenantFilterBuilder("")


def test_assert_filter_rejects_missing_tenant():
    bad = models.Filter(
        must=[models.FieldCondition(key="source", match=models.MatchValue(value="x"))]
    )
    with pytest.raises(AssertionError):
        assert_filter_has_tenant(bad, "acme")


def test_assert_filter_rejects_wrong_tenant():
    wrong = TenantFilterBuilder("tenantA").build()
    with pytest.raises(AssertionError):
        assert_filter_has_tenant(wrong, "tenantB")  # cross-tenant must fail
