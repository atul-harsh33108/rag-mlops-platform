"""evals_canary DAG (M3): a lightweight production canary eval that runs after each
corpus_version bump (Asset-triggered) and nightly. It asks a fixed set of golden
questions through the app /chat (include_contexts=true), asserts each answer is
non-empty with >=1 citation, and fails the DAG if the pass rate drops below 0.6 —
surfacing a regression fast.

The DEEP nightly RAGAS suite (reference-based metrics + Langfuse scoring) stays in
GitHub Actions (eval-nightly.yml, M2) — it needs the judge model + RAGAS deps not
present in the Airflow image. M7's production-sampled eval will post canary scores to
Langfuse properly; this DAG is the fast, always-on gate.
"""

from __future__ import annotations

import json
from datetime import datetime

import httpx
from airflow.sdk import DAG, task
from pipelines.dags.assets import APP_BASE, CORPUS_VERSION_BUMPED, DEFAULT_TENANT

# Fixed canary questions (subset of evals/golden_dataset.jsonl). Kept inline so the
# Airflow image needs no evals deps. Expand from the golden file at M7.
CANARY_QUESTIONS = [
    "How do I reset my password?",
    "How do I export my data?",
    "What are the supported integrations?",
    "How do I upgrade my plan?",
    "How do I contact support?",
]

PASS_THRESHOLD = 0.6  # fail the DAG below this — surfaces a regression within one reindex

with DAG(
    dag_id="evals_canary",
    # Asset-triggered after a reindex, AND nightly at 03:17 UTC (off-the-hour, see ADR).
    schedule=[CORPUS_VERSION_BUMPED],
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["mlops", "m3", "eval"],
) as dag:

    @task
    def run_canary() -> dict:
        results = []
        for q in CANARY_QUESTIONS:
            resp = httpx.post(
                f"{APP_BASE}/chat",
                json={
                    "tenant": DEFAULT_TENANT,
                    "question": q,
                    "stream": False,
                    "include_contexts": True,
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            body = resp.json()
            ok = bool(body.get("answer")) and len(body.get("citations", [])) >= 1
            results.append({"question": q, "ok": ok})
        passed = sum(1 for r in results if r["ok"])
        return {
            "score": passed / len(CANARY_QUESTIONS),
            "passed": passed,
            "total": len(CANARY_QUESTIONS),
            "results": results,
        }

    @task
    def gate(summary: dict) -> None:
        # Fail the DAG if the canary score drops below the threshold — surfaces a
        # regression fast (within one reindex cycle).
        if summary["score"] < PASS_THRESHOLD:
            raise ValueError(f"canary eval failed: {json.dumps(summary)}")
        print(f"canary eval passed: {json.dumps(summary)}")

    gate(run_canary())
