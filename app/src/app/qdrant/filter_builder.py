"""SECURITY-CRITICAL: build Qdrant filters from the authenticated tenant.

Every retriever path MUST go through `build_tenant_filter`. Clients never supply
filters — the server reads `tenant_id` from the (validated) auth context and emits
the Qdrant `Filter(must=[group_id == tenant_id])` that scopes retrieval to that
tenant's documents. CI (M2) asserts every search payload contains a `group_id`
filter; a missing filter is a security bug.

In M1 there is no real JWT yet; `tenant_id` comes from the request body and is
validated to exist in the `tenants` table. M6 replaces this with JWT claim extraction.
"""

from __future__ import annotations

from qdrant_client.http import models


class TenantFilterBuilder:
    """Builds Qdrant filters scoped to a tenant (and optionally extra constraints)."""

    def __init__(self, tenant_id: str) -> None:
        if not tenant_id:
            raise ValueError("tenant_id is required for every retrieval")
        self.tenant_id = tenant_id

    def build(self, *, extra: list[models.FieldCondition] | None = None) -> models.Filter:
        """Return a Filter that MUST match group_id == tenant_id (+ optional extras)."""
        must: list[models.FieldCondition] = [
            models.FieldCondition(
                key="group_id",
                match=models.MatchValue(value=self.tenant_id),
            )
        ]
        if extra:
            must.extend(extra)
        return models.Filter(must=must)

    def build_search_payload(self) -> dict:
        """Assertion helper: return the minimal filter dict so tests can assert RLS."""
        return {"must": [{"key": "group_id", "match": {"value": self.tenant_id}}]}


def assert_filter_has_tenant(filter_: models.Filter, tenant_id: str) -> None:
    """Called from tests / a request guard. Raises if the tenant filter is missing."""
    if not filter_ or not getattr(filter_, "must", None):
        raise AssertionError("Qdrant filter missing `must` clause — tenant isolation absent")
    for cond in filter_.must:
        if getattr(cond, "key", None) == "group_id":
            match = getattr(cond, "match", None)
            if match and getattr(match, "value", None) == tenant_id:
                return
    raise AssertionError(f"Qdrant filter does not scope to tenant {tenant_id!r}")
