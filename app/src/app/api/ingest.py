"""POST /ingest — add a document to a tenant's corpus (chunks → embed → upsert to Qdrant).

M1: synchronous single-doc ingest. M3: bulk ingest moves to the Airflow `ingest` DAG;
this endpoint stays for interactive/seed use but defers large batches to the DAG.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field
from qdrant_client.http import models

from app.clients.embeddings import EmbeddingClient
from app.config import get_settings
from app.db import ensure_tenant, session_context
from app.qdrant.client import ensure_collection, get_client

router = APIRouter(tags=["ingest"])

_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=512, chunk_overlap=64, separators=["\n\n", "\n", ". ", " "]
)


class IngestRequest(BaseModel):
    tenant: str = Field(..., min_length=1, max_length=64)
    source: str = Field(..., description="source label (doc title / url)")
    text: str = Field(..., min_length=1)
    doc_id: str | None = None


class IngestResponse(BaseModel):
    doc_id: str
    chunks: int


@router.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest) -> IngestResponse:
    s = get_settings()
    doc_id = req.doc_id or str(uuid.uuid4())

    async with session_context() as session:
        await ensure_tenant(session, req.tenant)

    chunks = _SPLITTER.split_text(req.text)
    if not chunks:
        raise HTTPException(status_code=400, detail="text produced no chunks")

    embedder = EmbeddingClient()
    embeddings = await embedder.embed(chunks)

    client = get_client()
    await ensure_collection(client)

    # Idempotent reindex (M3): delete this doc's prior chunks first so a changed doc
    # overwrites cleanly instead of accumulating orphaned old chunks. Point ids are
    # deterministic (uuid5 of tenant|doc_id|chunk_idx) so the upsert is a true overwrite.
    await client.delete(
        collection_name=s.qdrant_collection,
        points_selector=models.Filter(
            must=[
                models.FieldCondition(key="group_id", match=models.MatchValue(value=req.tenant)),
                models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
            ]
        ),
        wait=True,
    )

    points: list[models.PointStruct] = []
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings, strict=False)):
        vector: dict[str, Any] = {"dense": emb["dense"]}
        sp = emb.get("sparse")
        if sp and sp.get("indices"):
            vector["bm25"] = models.SparseVector(indices=sp["indices"], values=sp["values"])
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{req.tenant}|{doc_id}|{i}"))
        points.append(
            models.PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "text": chunk,
                    "source": req.source,
                    "doc_id": doc_id,
                    "chunk_idx": i,
                    "group_id": req.tenant,
                    "is_tenant": True,
                },
            )
        )

    # Batch upsert in chunks of 512 with wait=True (Airflow DAG does the same at M3).
    for i in range(0, len(points), 512):
        await client.upsert(
            collection_name=s.qdrant_collection, points=points[i : i + 512], wait=True
        )

    return IngestResponse(doc_id=doc_id, chunks=len(points))
