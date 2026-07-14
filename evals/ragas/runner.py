"""Offline RAGAS runner — the eval-driven-development gate.

Loads golden_dataset.jsonl → calls the app /chat (include_contexts=true) → builds a
RAGAS EvaluationDataset → runs metrics → pushes scores to Langfuse → prints P50/P90/P99
and exits non-zero on threshold regression.

Usage:
  uv run python ragas/runner.py --suite pr      # faithfulness + relevance (every PR)
  uv run python ragas/runner.py --suite nightly # full suite (nightly)
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml
from langchain_openai import ChatOpenAI
from ragas import EvaluationDataset
from ragas.metrics import (
    answer_correctness,
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "golden_dataset.jsonl"
THRESHOLDS = ROOT / "thresholds.yaml"
JUDGES = ROOT / "judges" / "config.yaml"

SUITES = {
    "pr": [faithfulness, answer_relevancy],
    "nightly": [faithfulness, answer_relevancy, context_precision, context_recall, answer_correctness],
}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def load_judge() -> ChatOpenAI:
    cfg = yaml.safe_load(JUDGES.read_text())["judge"]
    return ChatOpenAI(
        model=_env("JUDGE_MODEL", cfg.get("model", "qwen3:14b")),
        base_url=_env("JUDGE_BASE_URL", cfg.get("base_url", "").replace("${JUDGE_BASE_URL}", "")),
        api_key=_env("JUDGE_API_KEY", cfg.get("api_key", "").replace("${JUDGE_API_KEY}", "")) or "dummy",
        temperature=float(cfg.get("temperature", 0.0)),
    )


def call_app(question: str, base_url: str, tenant: str) -> dict[str, Any]:
    r = httpx.post(
        f"{base_url}/chat",
        json={"question": question, "tenant": tenant, "stream": False, "include_contexts": True},
        timeout=120.0,
    )
    r.raise_for_status()
    return r.json()


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=["pr", "nightly"], default="pr")
    ap.add_argument("--app-url", default=_env("APP_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--tenant", default=_env("EVAL_TENANT", "acme"))
    args = ap.parse_args()

    thresholds = yaml.safe_load(THRESHOLDS.read_text())[args.suite]
    rows = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    print(f"Loaded {len(rows)} golden Q&A triples; suite={args.suite}")

    samples: list[dict[str, Any]] = []
    for row in rows:
        try:
            resp = call_app(row["user_input"], args.app_url, args.tenant)
        except Exception as e:
            print(f"WARN: app call failed for '{row['user_input'][:40]}…': {e}", file=sys.stderr)
            continue
        samples.append(
            {
                "user_input": row["user_input"],
                "response": resp["answer"],
                "retrieved_contexts": resp.get("contexts", []),
                "reference": row["reference"],
            }
        )
    if not samples:
        print("ERROR: no samples produced — is the app running at " + args.app_url + "?", file=sys.stderr)
        return 2

    ds = EvaluationDataset(samples)
    # NOTE: a real embeddings model is needed for context_precision/recall/relevancy.
    # For the scaffold we pass only the LLM judge; add ragas embeddings (e.g. TEI via
    # langchain HuggingFaceEmbeddings) when running the nightly suite end-to-end.
    result = ds.evaluate(metrics=SUITES[args.suite], llm=load_judge())

    # result is a DataFrame-like object; convert to dict of metric -> list of scores.
    df = result.to_pandas() if hasattr(result, "to_pandas") else result
    metrics_run = [m.name for m in SUITES[args.suite]]
    failed = False
    for m in metrics_run:
        vals = [float(x) for x in df[m].tolist() if x is not None]
        p50, p90, p99 = percentile(vals, 0.5), percentile(vals, 0.9), percentile(vals, 0.99)
        thr = thresholds.get(m, 0.0)
        ok = p50 >= float(thr)
        print(f"{m:24s} P50={p50:.3f} P90={p90:.3f} P99={p99:.3f}  gate={thr:.2f}  {'PASS' if ok else 'FAIL'}")
        if not ok:
            failed = True

    # TODO: push scores to Langfuse traces (LANGFUSE_PUBLIC_KEY/SECRET_KEY set).
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())