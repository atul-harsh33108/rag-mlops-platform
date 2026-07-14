"""DeepEval PR gate — fails the build on faithfulness regression.

Run via the `deepeval test run` CLI (which supports --fail-on-threshold-breach) or plain
pytest. The judge model is configured by env: OPENAI_BASE_URL (LiteLLM/Ollama), OPENAI_API_KEY,
and the model name below. Deepeval reads those env vars automatically.

    APP_URL=http://127.0.0.1:8000 \
    OPENAI_BASE_URL=http://ollama:11434/v1 OPENAI_API_KEY=dummy \
    JUDGE_MODEL=qwen3:14b \
    uv run pytest deepeval --fail-on-threshold-breach
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
import yaml
from deepeval import assert_test
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
from deepeval.test_case import LLMTestCase

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "golden_dataset.jsonl"
THRESHOLDS = yaml.safe_load((ROOT / "thresholds.yaml").read_text())["pr_gate"]

APP_URL = os.environ.get("APP_URL", "http://127.0.0.1:8000")
TENANT = os.environ.get("EVAL_TENANT", "acme")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "qwen3:14b")

ROWS = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]


def _call_app(question: str) -> dict:
    r = httpx.post(
        f"{APP_URL}/chat",
        json={"question": question, "tenant": TENANT, "stream": False, "include_contexts": True},
        timeout=120.0,
    )
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def faithfulness_metric() -> FaithfulnessMetric:
    return FaithfulnessMetric(threshold=float(THRESHOLDS["faithfulness"]), model=JUDGE_MODEL)


@pytest.fixture(scope="module")
def relevancy_metric() -> AnswerRelevancyMetric:
    return AnswerRelevancyMetric(threshold=float(THRESHOLDS["answer_relevancy"]), model=JUDGE_MODEL)


@pytest.mark.parametrize("row", ROWS, ids=[r["user_input"][:30] for r in ROWS])
def test_rag_answer_is_faithful_and_relevant(row, faithfulness_metric, relevancy_metric):
    """Every golden question must get a faithful, relevant answer — or the build fails."""
    try:
        resp = _call_app(row["user_input"])
    except Exception as e:
        pytest.fail(f"app unreachable at {APP_URL}: {e}")

    tc = LLMTestCase(
        input=row["user_input"],
        actual_output=resp["answer"],
        retrieval_context=resp.get("contexts", []) or ["<no context retrieved>"],
        expected_output=row["reference"],
    )
    assert_test(tc, [faithfulness_metric, relevancy_metric])