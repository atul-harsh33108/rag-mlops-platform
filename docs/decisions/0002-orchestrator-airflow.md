# ADR 0002 — Airflow 3.x for orchestration

**Status:** Accepted

## Context

Candidates for RAG ingestion / re-indexing / eval pipelines: Airflow 3.x, Prefect 3.7.x, Dagster 1.13.x. 2026 research favors Dagster's asset model for greenfield RAG (corpus/chunks/embeddings/index/evals as lineage-tracked assets with freshness policies + incremental re-materialization).

## Decision

Use **Airflow 3.x** (user's pick). Model ingestion as DAGs with **Dataset triggers** for corpus-change sensing. Use the Apache Airflow chart v1.13.1 (Bitnami pinned to `bitnamilegacy`).

## Rationale

- User explicitly selected Airflow/Prefect; Airflow retained for ecosystem maturity and hiring signal.
- Airflow 3 added asset-aware scheduling (Datasets), narrowing the gap with Dagster for our re-index-on-change need.

## Consequences

- We lose Dagster's incremental "skip re-materialize when upstream unchanged" optimization — mitigate by tracking a `corpus_version` and only re-embedding changed chunks (content-hash compare in the chunk DAG).
- XCom payload limit (~48KB): pass S3 keys / DB references, never payloads.
- If asset lineage becomes a real pain, reassess Dagster at M4.