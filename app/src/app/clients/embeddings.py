"""TEI client: dense + sparse embeddings for BGE-M3.

BGE-M3 returns dense (1024-d) AND sparse (token-id -> weight) vectors in one call
(via the `/embed` endpoint with `--sparse` enabled on the server, exposed as the
`/embed` `sparse` field). We use dense for the HNSW vector and sparse for the BM25
sparse vector named `bm25` in Qdrant.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings


class EmbeddingClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        s = get_settings()
        self._base = base_url or f"http://{s.tei_host}:{s.tei_port}"
        self._timeout = timeout

    async def embed(self, texts: list[str]) -> list[dict[str, Any]]:
        """Return per-text {dense: list[float], sparse: {indices, values}}.

        Falls back gracefully: if the TEI build doesn't return sparse, sparse=None
        and the retriever uses dense-only hybrid (BM25 path skipped).
        """
        if not texts:
            return []
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            resp = await c.post(
                f"{self._base}/embed",
                json={"inputs": texts, "truncate": True},
            )
            resp.raise_for_status()
            data = resp.json()
        # TEI returns either a list of dicts (with sparse) or a list of plain vectors (dense-only).
        out: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict) and "dense" in item:
                sparse = item.get("sparse")
                out.append({"dense": item["dense"], "sparse": sparse})
            elif isinstance(item, dict) and "embeddings" in item:  # {"embeddings": [...]}
                out.append({"dense": item["embeddings"], "sparse": item.get("sparse")})
            else:  # plain vector
                out.append({"dense": item, "sparse": None})
        return out

    async def embed_one(self, text: str) -> dict[str, Any]:
        return (await self.embed([text]))[0]

    async def rerank(
        self, query: str, documents: list[str], top_n: int | None = None
    ) -> list[dict[str, Any]]:
        """Cross-encoder rerank via TEI `/rerank`. Returns [{index, score}, ...] sorted desc."""
        if not documents:
            return []
        payload: dict[str, Any] = {"query": query, "texts": documents}
        if top_n is not None:
            payload["top_n"] = top_n
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            resp = await c.post(f"{self._base}/rerank", json=payload)
            resp.raise_for_status()
            return resp.json()  # [{"index": int, "score": float}, ...]
