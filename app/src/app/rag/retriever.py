"""Hybrid retrieval: dense (BGE-M3) + sparse (BM25 via Qdrant sparse vectors),
fused by Qdrant's RRF, then cross-encoder reranked by BGE-reranker-v2-m3 (TEI),
tenant-scoped via filter_builder. Exposed as a LangChain BaseRetriever so LangGraph
(M6 agentic flows) can consume it (ADR 0003).
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from qdrant_client.http import models

from app.clients.embeddings import EmbeddingClient
from app.config import get_settings
from app.qdrant.client import ensure_collection, get_client
from app.qdrant.filter_builder import TenantFilterBuilder


class HybridRetriever:
    """Async-first hybrid retriever. The FastAPI /chat path uses `retrieve` directly."""

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.filter_builder = TenantFilterBuilder(tenant_id)
        self.embedder = EmbeddingClient()
        self._client = get_client()
        s = get_settings()
        self.collection = s.qdrant_collection
        self.retrieve_top_k = s.retrieve_top_k
        self.rerank_top_k = s.rerank_top_k

    async def retrieve(self, question: str) -> list[dict[str, Any]]:
        """Return reranked chunks: [{text, source, doc_id, chunk_idx, score}]."""
        await ensure_collection(self._client)
        emb = await self.embedder.embed_one(question)
        dense = emb["dense"]
        sparse = emb.get("sparse")
        tenant_filter = self.filter_builder.build()

        # --- Hybrid query via Qdrant RRF fusion (dense + sparse prefetches). ---
        # Two paths:
        #  - sparse available: two prefetches (dense + bm25) fused by RRF; top-level
        #    query is None and `fusion` fuses the prefetches.
        #  - dense-only: a single top-level dense query, no prefetch, no fusion.
        query: Any = None
        using: str | None = None
        prefetch: list[models.Prefetch] = []
        fusion: models.FusionQuery | None = None
        if sparse and sparse.get("indices"):
            sparse_vec = models.SparseVector(indices=sparse["indices"], values=sparse["values"])
            prefetch = [
                models.Prefetch(query=dense, using="dense", limit=self.retrieve_top_k),
                models.Prefetch(query=sparse_vec, using="bm25", limit=self.retrieve_top_k),
            ]
            fusion = models.FusionQuery(fusion=models.Fusion.RRF)
        else:
            query = dense
            using = "dense"

        points = await self._client.query_points(
            collection_name=self.collection,
            query=query,
            using=using,
            prefetch=prefetch,
            fusion=fusion,
            query_filter=tenant_filter,
            limit=self.retrieve_top_k,
            with_payload=True,
            with_vectors=False,
        )
        candidates = points.points
        if not candidates:
            return []

        docs = [p.payload.get("text", "") or "" for p in candidates]
        reranked = await self.embedder.rerank(question, docs, top_n=self.rerank_top_k)

        out: list[dict[str, Any]] = []
        for r in reranked[: self.rerank_top_k]:
            idx = r["index"]
            payload = candidates[idx].payload or {}
            out.append(
                {
                    "text": payload.get("text", ""),
                    "source": payload.get("source", "unknown"),
                    "doc_id": payload.get("doc_id", ""),
                    "chunk_idx": payload.get("chunk_idx", 0),
                    "score": float(r.get("score", 0.0)),
                    "group_id": payload.get("group_id", self.tenant_id),
                }
            )
        return out


class LangChainHybridRetriever(BaseRetriever):
    """LangChain adapter so LangGraph can use this retriever as a tool (ADR 0003).

    LangChain BaseRetriever is pydantic v1-style; declare the tenant id as a field.
    """

    tenant_id: str

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        import asyncio

        chunks = asyncio.get_event_loop().run_until_complete(
            HybridRetriever(self.tenant_id).retrieve(query)
        )
        return [
            Document(page_content=c["text"], metadata={k: v for k, v in c.items() if k != "text"})
            for c in chunks
        ]

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        chunks = await HybridRetriever(self.tenant_id).retrieve(query)
        return [
            Document(page_content=c["text"], metadata={k: v for k, v in c.items() if k != "text"})
            for c in chunks
        ]
