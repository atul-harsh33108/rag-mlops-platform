"""ingest_full DAG — the corpus ingest pipeline (M3): list corpus files → fan out
chunk_embed_index over them → verify Qdrant point count matches → produce the
`corpus_indexed` Asset (which triggers reindex_on_change).

The /ingest endpoint does chunk+embed+upsert; this DAG orchestrates the batch and adds
the production safeguards the synchronous endpoint lacks: dynamic fan-out, a Qdrant
count sensor (count_points vs expected), and the Asset that drives cache invalidation.

Trigger:  `task ingest:full`  (or Airflow UI / API).
"""

from __future__ import annotations

import glob
import os
from datetime import datetime

import httpx
from airflow.sdk import DAG, task
from pipelines.dags.assets import CORPUS_DIR, CORPUS_INDEXED, DEFAULT_TENANT, QDRANT_BASE
from pipelines.dags.chunk_embed_index import chunk_embed_index

with DAG(
    dag_id="ingest_full",
    schedule=None,  # manual / triggered via `task ingest:full`
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["mlops", "m3", "ingest"],
    default_args={"retries": 1},
) as dag:

    @task
    def list_corpus_files() -> list[str]:
        """Return corpus file paths (small list of strings — safe XCom, <48KB)."""
        patterns = ("**/*.md", "**/*.txt")
        files: list[str] = []
        for pat in patterns:
            files.extend(glob.glob(os.path.join(CORPUS_DIR, pat), recursive=True))
        return sorted(files)

    @task
    def total_chunks(per_doc: list[int]) -> int:
        return sum(per_doc)

    @task(retries=6, retry_delay=30)
    def verify_count(expected: int) -> int:
        """Sensor: poll Qdrant until points_count >= expected (idempotent reindex)."""
        resp = httpx.get(f"{QDRANT_BASE}/collections/docs", timeout=30.0)
        resp.raise_for_status()
        actual = int(resp.json()["result"]["points_count"])
        if expected > 0 and actual < expected:
            raise ValueError(f"qdrant count {actual} < expected {expected}; retrying")
        return actual

    @task(outlets=[CORPUS_INDEXED])
    def publish(expected: int, actual: int) -> None:
        # Producing the Asset schedules reindex_on_change (corpus_version bump).
        print(f"corpus indexed: expected={expected} actual={actual} tenant={DEFAULT_TENANT}")

    files = list_corpus_files()
    # Dynamic map the TaskGroup over all corpus files (Airflow fans these out).
    per_doc = chunk_embed_index.expand(file_path=files)
    expected = total_chunks(per_doc)
    actual = verify_count(expected)
    publish(expected, actual)
