"""Reusable TaskGroup: chunk → embed → index one corpus document.

The FastAPI `/ingest` endpoint does chunk+embed+upsert in one call (LangChain splitter
→ BGE-M3 via TEI → Qdrant). This TaskGroup wraps the per-doc HTTP call so the ingest DAG
can `.expand` it over the corpus and the reindex DAG can reuse it.

Scaling note (M3→M5): for >100k docs, swap the per-doc HTTP fan-out for a Ray-in-process
batch (`ray.init()` + `ray.put`) so embeddings are batched across cores/nodes. Kept as a
sequential HTTP fan-out here — correct and shippable for the demo corpus (~500 docs).
"""

from __future__ import annotations

from pathlib import Path

import httpx
from airflow.sdk import task, task_group
from pipelines.dags.assets import APP_BASE, DEFAULT_TENANT


@task
def ingest_doc(file_path: str) -> int:
    """Ingest one document; return the chunk count (small XCom — just an int)."""
    path = Path(file_path)
    text = path.read_text(encoding="utf-8")
    source = path.stem
    # doc_id is derived from the filename so re-ingest is an idempotent overwrite
    # (ingest.py deletes prior chunks for this doc_id before upserting).
    doc_id = f"file:{source}"
    resp = httpx.post(
        f"{APP_BASE}/ingest",
        json={"tenant": DEFAULT_TENANT, "source": source, "text": text, "doc_id": doc_id},
        timeout=180.0,
    )
    resp.raise_for_status()
    return int(resp.json()["chunks"])


@task_group(group_id="chunk_embed_index")
def chunk_embed_index(file_path: str) -> int:
    """Ingest one document; return the chunk count."""
    return ingest_doc(file_path)
