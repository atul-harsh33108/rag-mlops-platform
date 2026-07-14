# Evals — the gate that makes this eval-driven, not vibe-driven

Two runners, both driven by `golden_dataset.jsonl` (versioned triples: question,
reference answer, expected source) and `thresholds.yaml`:

| Runner | When | Metrics | Gate |
|---|---|---|---|
| `deepeval/test_rag_gate.py` | every PR | faithfulness + answer relevancy | hard fail below 0.80 / 0.75 |
| `ragas/runner.py --suite nightly` | nightly | + context precision/recall, answer correctness | P50 ≥ threshold |

Scores are pushed onto Langfuse traces (M2 wiring) so quality trends next to cost/latency
in the Grafana dashboard. Track **P50/P90/P99, not means** — means hide tail regressions.

## Run locally

```bash
cd evals && uv sync
# app + judge (Ollama) must be up: `task dev:up core,ai`
APP_URL=http://127.0.0.1:8000 \
OPENAI_BASE_URL=http://127.0.0.1:11434/v1 OPENAI_API_KEY=dummy \
JUDGE_MODEL=qwen3:14b \
uv run python ragas/runner.py --suite pr

# DeepEval gate:
APP_URL=http://127.0.0.1:8000 OPENAI_BASE_URL=http://127.0.0.1:11434/v1 \
OPENAI_API_KEY=dummy JUDGE_MODEL=qwen3:14b \
uv run pytest deepeval
```

## Discipline (pitfalls that bite)
- **Pin the judge model + version + temperature 0** (`judges/config.yaml`) — judge drift is silent.
- **Golden set must grow** — start ≥100 triples; auto-capture production failures as new cases.
- **Held-out partitions** to prevent overfitting to the golden set.
- **Cost-tier** the suite: faithfulness+relevance on every PR (~cheap), full suite nightly.
- **Corpus-version gate**: re-indexing (M3) bumps `corpus_version`, invalidating the semantic
  cache; the golden eval must re-run after any corpus/prompt/model change before promote.