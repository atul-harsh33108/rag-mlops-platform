# ADR 0007: Orchestration with Airflow 3.x (Task SDK + Assets)

Date: 2026-07-14
Status: Accepted

## Context

Milestone 3 needs to orchestrate the corpus lifecycle: ingest (chunk → embed → index),
corpus-change sensing, `corpus_version` bump + cache invalidation, and a canary eval.
The plan evaluated Airflow 3.x vs Dagster; the user kept Airflow (original pick).

Airflow 3.0 (AIP-72) shipped a major API change: DAG authoring moved to the
`airflow.sdk` namespace (the "Task SDK"), `Dataset` was renamed `Asset`, the
`airflow` webserver became `airflow api-server`, `airflow dag-processor` must run
independently, the Sequential executor was removed (use LocalExecutor), and
`PythonOperator` moved to `apache-airflow-providers-standard`. We author DAGs against
the new `airflow.sdk` public interface so they are forward-compatible.

## Decision

- Author DAGs with `from airflow.sdk import DAG, task, task_group, Asset` (TaskFlow API).
- Drive the reindex → eval chain with **Assets** (data-aware scheduling), not cron:
  `ingest_full` produces `corpus_indexed` → `reindex_on_change` consumes it and produces
  `corpus_version_bumped` → `evals_canary` consumes that (and also runs nightly).
- DAGs are decoupled from the app: they call the FastAPI `/ingest` + `/chat` over HTTP
  (the app owns chunk/embed/index logic). No shared Python import between the Airflow
  image and the app image — loose coupling, independent dep sets.
- `corpus_version` is bumped under a Postgres **advisory lock** so concurrent reindexes
  serialize; the semantic cache key includes `corpus_version`, so the bump invalidates
  all caches automatically.
- Local dev: `airflow standalone` (one process, sqlite + LocalExecutor). Prod (M4/M5):
  Bitnami Airflow chart with Postgres + KubernetesExecutor — **same DAGs, no edits**
  (the Task SDK is runtime-portable).

## Consequences

- DAGs must use `airflow.sdk` imports; legacy `from airflow.models import DAG` is
  deprecated and will break. A `ruff check --select AIR301` upgrade check guards this.
- `PythonOperator` is not in core; we use the `@task` decorator (TaskFlow) instead.
- Ray-based parallel embedding is deferred to M5 scale (>100k docs); M3 uses an HTTP
  fan-out with Airflow dynamic mapping (`.expand`), correct for the ~500-doc demo corpus.
- The canary eval DAG posts scores to Langfuse via the OTel collector; the full
  reference-based RAGAS suite stays in GitHub Actions (eval-nightly) — it needs the
  judge model + RAGAS deps not present in the Airflow image.

## Alternatives considered

- **Dagster**: cleaner asset model + Pythonic config, but the user kept Airflow and the
  ecosystem/Bitnami chart maturity favors Airflow for this stack.
- **Prefect**: simpler, but weaker Dataset/Asset story and less K8s chart maturity.
- **Cron + scripts**: rejected — no provenance, no retries, no Asset-driven reindex chain.