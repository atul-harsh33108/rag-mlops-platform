# ADR 0011 — Server-side usage metering + reconciliation (streaming under-count fix)

**Status:** Accepted

## Decision

Record the **real** token usage of every `/chat` turn server-side in `usage_events`, captured
from the provider's final streamed chunk (`stream_options.include_usage`), and run a daily
reconciliation DAG that compares it against `LiteLLM_SpendLogs` (and Langfuse usage as a
witness), alerting on >5% divergence. When the provider gives no usage (Ollama), estimate and
flag the row `estimated=TRUE`.

## Rationale

- **LiteLLM under-counts streamed output.** When a client disconnects mid-stream, LiteLLM
  counts what it *proxied*, not what the model *emitted* — an 8-15% gap on disconnects. If we
  invoiced straight off `LiteLLM_SpendLogs`, we'd systematically under-bill. The app sees the
  full final-chunk `usage` (the provider accounts for the whole completion), so it's the
  correct source of truth for billing.
- **`stream_options.include_usage` is the cheap fix.** OpenAI/LiteLLM/vLLM emit a final chunk
  with `usage` when asked. One field, no extra round-trip. Ollama ignores it — hence the
  `estimated` flag so the reconciliation DAG knows those rows are approximate and can weight
  them out of the divergence calc when needed.
- **Three witnesses, one truth.** `usage_events` (app), `LiteLLM_SpendLogs` (gateway),
  Langfuse `usage` (observability). Any two diverging >5% is a bug somewhere — the
  reconciliation DAG fires `RagUsageDivergenceHigh` to Alertmanager and writes a
  `regression_alerts` row so Grafana can show the history.
- **Defensible invoices.** Reconciliation runs *before* Lago invoice generation; a
  backfill billable-metric event closes the LiteLLM gap so the invoice matches what the model
  actually produced. Without this, the Lago→Stripe invoice is undefendable against a
  tenant audit.

## Consequences

- **Extra DB write per turn.** One `usage_events` insert per `/chat` (after the stream
  completes, off the hot path). Negligible vs. the LLM call cost; indexed by tenant+month.
- **Estimated rows are noisy.** Ollama/local-dev rows use a ~4-char/token estimate. In prod
  (vLLM/Bedrock via LiteLLM) `include_usage` is supported, so `estimated_frac` should be ~0;
  a rising `estimated_frac` in prod is itself a signal (provider stopped returning usage).
- **Reconciliation is daily, not real-time.** A divergence is caught within ~24h. That's fine
  for billing (invoices are monthly); it's NOT a substitute for the real-time hard cap, which
  the app enforces pre-generation (`spend.py`).
- **`request_id` joins to Langfuse.** `usage_events.request_id` is the app's trace id, so the
  reconciliation DAG can pull the Langfuse witness per-turn when needed.

## Revisit trigger

Re-evaluate if (a) a provider makes `include_usage` unreliable and `estimated_frac` climbs in
prod (add a tiktoken-based exact count), or (b) we move to real-time metering (stream the
`usage_events` insert + cap check to a per-turn event bus), or (c) divergence consistently
<1% (relax the daily cadence to weekly).