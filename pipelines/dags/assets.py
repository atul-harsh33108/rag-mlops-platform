"""Shared Airflow Assets (formerly Datasets in Airflow 2.x) + DAG constants.

Assets are the data-driven trigger mechanism: producing an Asset in one DAG schedules
any DAG whose `schedule=[Asset(...)]` consumes it. This wires the corpus-change →
reindex → eval chain (M3) without cron coupling.

  ingest_full ──produces──> corpus_indexed
       │
  reindex_on_change ──consumes corpus_indexed ──produces──> corpus_version_bumped
       │
  evals_canary ──consumes corpus_version_bumped (also nightly cron)
"""

from __future__ import annotations

import os

from airflow.sdk import Asset

# Network name of the FastAPI app service on the compose `mlops-net` network.
APP_BASE = os.getenv("APP_BASE_URL", "http://app:8000")
QDRANT_BASE = os.getenv("QDRANT_BASE_URL", "http://qdrant:6333")
DEFAULT_TENANT = os.getenv("DEFAULT_TENANT", "acme")

# The metadata Postgres (DATABASE_URL) for corpus_version bump under advisory lock.
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://mlops:CHANGE_ME@postgres:5432/mlops")

# Mounted read-only from data/corpus on the host (see compose.orchestration.yml).
CORPUS_DIR = os.getenv("CORPUS_DIR", "/opt/airflow/corpus")

# Assets.
CORPUS_INDEXED = Asset("mlops://corpus/indexed")
CORPUS_VERSION_BUMPED = Asset("mlops://corpus/version_bumped")
