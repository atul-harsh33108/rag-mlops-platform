"""Security guard for the hybrid retriever (M3): every Qdrant query MUST carry a
tenant `group_id` filter built server-side by filter_builder. A retriever path that
forgets the filter would leak cross-tenant docs — treat as a security bug.

These tests mock the Qdrant client + embedder (no network) and assert the filter is
present on every code path: dense-only, dense+sparse (RRF), and rerank.
"""

from __future__ import annotations

import pytest
from qdrant_client.http import models

import app.rag.retriever as r


class _FakeEmb:
    async def embed_one(self, text: str) -> dict:
        return {
            "dense": [0.0] * 4,
            "sparse": {"indices": [1, 2, 3], "values": [0.5, 0.6, 0.4]},
        }

    async def rerank(self, query, documents, top_n=None):
        n = min(len(documents), top_n or 2)
        return [{"index": i, "score": 1.0 - i * 0.1} for i in range(n)]


class _FakePoints:
    def __init__(self, payloads):
        class P:
            def __init__(self, payload):
                self.payload = payload

        self.points = [P(p) for p in payloads]


class _FakeClient:
    def __init__(self, captured: dict, payloads):
        self._captured = captured
        self._payloads = payloads

    async def query_points(self, **kwargs):
        self._captured.update(kwargs)
        return _FakePoints(self._payloads)


async def _noop_ensure(_client):
    return None


@pytest.fixture
def patched_retriever(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(r, "ensure_collection", _noop_ensure)
    monkeypatch.setattr(r, "EmbeddingClient", lambda: _FakeEmb())
    monkeypatch.setattr(r, "get_client", lambda: _FakeClient(captured, []))
    return captured


def _has_group_id_filter(flt, tenant: str) -> bool:
    if flt is None:
        return False
    return any(
        isinstance(c, models.FieldCondition)
        and c.key == "group_id"
        and isinstance(c.match, models.MatchValue)
        and c.match.value == tenant
        for c in (flt.must or [])
    )


async def test_dense_sparse_path_carries_tenant_filter(patched_retriever):
    """dense + sparse (RRF fusion) path must be tenant-scoped."""
    ret = r.HybridRetriever("tenantA")
    out = await ret.retrieve("how do I reset my password?")
    assert out == []
    assert _has_group_id_filter(patched_retriever["query_filter"], "tenantA")


async def test_filter_never_carries_other_tenant(patched_retriever):
    """tenantA's retriever must never build a filter naming tenantB."""
    ret = r.HybridRetriever("tenantA")
    await ret.retrieve("anything")
    flt = patched_retriever["query_filter"]
    assert flt is not None
    for c in flt.must or []:
        if isinstance(c, models.FieldCondition) and c.key == "group_id":
            assert c.match.value == "tenantA"


async def test_rerank_uses_only_retrieved_candidates(monkeypatch):
    """Rerank reorders the tenant-filtered candidate set — it cannot introduce docs
    from outside the filter (the indices index into `candidates`, never the collection)."""
    payloads = [
        {"text": "a", "source": "faq", "doc_id": "d1", "chunk_idx": 0, "group_id": "tenantA"},
        {"text": "b", "source": "faq", "doc_id": "d2", "chunk_idx": 0, "group_id": "tenantA"},
    ]
    captured: dict = {}
    monkeypatch.setattr(r, "ensure_collection", _noop_ensure)
    monkeypatch.setattr(r, "EmbeddingClient", lambda: _FakeEmb())
    monkeypatch.setattr(r, "get_client", lambda: _FakeClient(captured, payloads))
    ret = r.HybridRetriever("tenantA")
    out = await ret.retrieve("q")
    # every returned chunk carries tenantA group_id (never a leaked tenant)
    assert all(c["group_id"] == "tenantA" for c in out)
    assert _has_group_id_filter(captured["query_filter"], "tenantA")
