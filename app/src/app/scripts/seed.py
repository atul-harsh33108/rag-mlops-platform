"""Seed the demo corpus into Qdrant. Run inside the app container or locally with uv:
    uv run python -m app.scripts.seed

Idempotent: re-running upserts new points (existing points are not de-duped by doc_id;
M3 Airflow DAG does content-hash-based upsert/replace). For a clean reseed, delete the
collection first: `client.delete_collection('docs')`.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client.http import models

from app.clients.embeddings import EmbeddingClient
from app.config import get_settings
from app.db import ensure_tenant, session_context
from app.qdrant.client import ensure_collection, get_client
from app.scripts.seed_corpus import CORPUS, TENANT

_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=512, chunk_overlap=64, separators=["\n\n", "\n", ". ", " "]
)


async def main() -> None:
    s = get_settings()
    embedder = EmbeddingClient()
    client = get_client()
    await ensure_collection(client)

    async with session_context() as session:
        await ensure_tenant(session, TENANT, name="Acme Demo")

    total_chunks = 0
    for source, text in CORPUS:
        chunks = _SPLITTER.split_text(text)
        if not chunks:
            continue
        embeddings = await embedder.embed(chunks)
        points: list[models.PointStruct] = []
        doc_id = str(uuid.uuid4())
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings, strict=False)):
            vector: dict[str, Any] = {"dense": emb["dense"]}
            sp = emb.get("sparse")
            if sp and sp.get("indices"):
                vector["bm25"] = models.SparseVector(indices=sp["indices"], values=sp["values"])
            points.append(
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={
                        "text": chunk,
                        "source": source,
                        "doc_id": doc_id,
                        "chunk_idx": i,
                        "group_id": TENANT,
                        "is_tenant": True,
                    },
                )
            )
        for i in range(0, len(points), 512):
            await client.upsert(
                collection_name=s.qdrant_collection, points=points[i : i + 512], wait=True
            )
        total_chunks += len(points)

    count = await client.count(collection_name=s.qdrant_collection, exact=True)
    print(f"Seeded {len(CORPUS)} documents ({total_chunks} chunks) for tenant '{TENANT}'.")
    print(f"Qdrant collection '{s.qdrant_collection}' now holds {count.count} points.")


if __name__ == "__main__":
    asyncio.run(main())
