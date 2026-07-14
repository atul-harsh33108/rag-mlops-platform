"""Qdrant client + collection setup. The collection carries a `group_id` payload
index from day one so tenant RLS (filter_builder) is fast and always-on."""

from __future__ import annotations

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.config import get_settings


def get_client() -> AsyncQdrantClient:
    s = get_settings()
    return AsyncQdrantClient(
        host=s.qdrant_host,
        port=s.qdrant_port,
        api_key=s.qdrant_api_key,
        prefer_grpc=False,
    )


async def ensure_collection(client: AsyncQdrantClient) -> None:
    """Create the docs collection with dense + sparse vectors + tenant payload index.

    BGE-M3 gives dense (1024-d) + sparse. We name the sparse vector `bm25` so hybrid
    retrieval (retriever.py) can fuse dense + sparse via Qdrant's RRF query.
    """
    s = get_settings()
    if await client.collection_exists(s.qdrant_collection):
        return
    await client.create_collection(
        collection_name=s.qdrant_collection,
        vectors_config={
            "dense": models.VectorParams(
                size=s.embedding_dim,
                distance=models.Distance.COSINE,
                on_disk=False,
            )
        },
        sparse_vectors_config={
            "bm25": models.SparseVectorParams(index=models.SparseIndexParams(on_disk=False))
        },
    )
    # Payload indexes — the tenant RLS filter and metadata filters prune during HNSW traversal.
    for field, schema in [
        ("group_id", models.PayloadSchemaType.KEYWORD),
        ("is_tenant", models.PayloadSchemaType.BOOL),
        ("source", models.PayloadSchemaType.KEYWORD),
        ("doc_id", models.PayloadSchemaType.KEYWORD),
        ("chunk_idx", models.PayloadSchemaType.INTEGER),
    ]:
        await client.create_payload_index(
            collection_name=s.qdrant_collection,
            field_name=field,
            field_schema=schema,
        )
