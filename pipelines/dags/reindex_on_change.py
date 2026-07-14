"""reindex_on_change DAG (M3): consume the `corpus_indexed` Asset, bump `corpus_version`
under a Postgres advisory lock (so concurrent reindexes serialize), verify Qdrant is
healthy, then produce `corpus_version_bumped` — which invalidates the semantic cache
(cache keys include corpus_version) and triggers the canary eval.

Correctness: the version bump happens AFTER ingest_full has upserted the new corpus
(producing corpus_indexed). This means a tiny window where new points are queryable but
cached answers still serve the old version — acceptable for a support assistant (caches
are question-keyed; new content only helps NEW questions). For strict consistency, swap
to a blue/green collection + atomic alias swap (documented as M5 hardening).

The advisory lock (pg_advisory_xact_lock on a stable hash) guarantees only one reindex
bumps the version at a time even if ingest_full fires twice.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import psycopg
from airflow.sdk import DAG, task
from pipelines.dags.assets import (
    CORPUS_INDEXED,
    CORPUS_VERSION_BUMPED,
    DATABASE_URL,
    QDRANT_BASE,
)

with DAG(
    dag_id="reindex_on_change",
    schedule=[CORPUS_INDEXED],  # Asset-triggered (was Dataset in Airflow 2.x)
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["mlops", "m3", "reindex"],
) as dag:

    @task
    def bump_corpus_version() -> int:
        """Atomically increment corpus_version under an advisory lock; return new version."""
        # Stable lock key (int32) derived from a fixed string — keeps it small for PG.
        lock_key = abs(hash("mlops:corpus_version")) % (2**31)
        sql = """
        BEGIN;
        SELECT pg_advisory_xact_lock(%s);
        UPDATE corpus_state
           SET corpus_version = corpus_version + 1, updated_at = now()
         WHERE id = 1
         RETURNING corpus_version;
        COMMIT;
        """
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql, (lock_key,))
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("corpus_state row missing — seed the DB")
            return int(row[0])

    @task(retries=4, retry_delay=20)
    def verify_healthy(version: int) -> int:
        """Qdrant health gate before publishing the version bump."""
        resp = httpx.get(f"{QDRANT_BASE}/collections/docs", timeout=30.0)
        resp.raise_for_status()
        status = resp.json()["result"]["status"]
        if status != "green":
            raise ValueError(f"qdrant not green (status={status}); retrying")
        return version

    @task(outlets=[CORPUS_VERSION_BUMPED])
    def publish(version: int) -> None:
        # Producing this Asset invalidates caches (key includes corpus_version) and
        # schedules evals_canary.
        print(f"corpus_version bumped to {version}; caches invalidated")

    new_version = bump_corpus_version()
    healthy = verify_healthy(new_version)
    publish(healthy)
