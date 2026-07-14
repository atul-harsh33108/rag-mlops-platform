-- Billing + metering + sampled-eval schema (M7). UTC enforced by container env.
-- Extends the M1 tenants table and M6 tenant_api_keys table with plan/budget fields, and
-- adds the tables that make this a billable SaaS: server-side usage metering (the fix for
-- LiteLLM streaming under-counting), sampled production evals, and regression alerts.
SET TIME ZONE 'UTC';

-- ---------------------------------------------------------------------------
-- tenants: add billing identity + budget. Plan lives on the tenant (the Clerk org); keys
-- inherit the tenant plan unless a key carries its own (tighter) budget.
-- ---------------------------------------------------------------------------
ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS lago_customer_id      TEXT,
    ADD COLUMN IF NOT EXISTS lago_subscription_id  TEXT,
    ADD COLUMN IF NOT EXISTS stripe_customer_id    TEXT,
    ADD COLUMN IF NOT EXISTS monthly_budget_usd    NUMERIC(10,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS budget_hard_pct       SMALLINT      NOT NULL DEFAULT 100, -- cap vs budget
    ADD COLUMN IF NOT EXISTS updated_at            TIMESTAMPTZ   NOT NULL DEFAULT now();

-- Plan -> default budget. The app's plans module (app/billing/plans.py) is the source of
-- truth for limits/rate; this just keeps the DB consistent on plan change.
UPDATE tenants SET monthly_budget_usd = 50.00  WHERE plan = 'free'       AND monthly_budget_usd = 0;
UPDATE tenants SET monthly_budget_usd = 500.00 WHERE plan = 'pro'        AND monthly_budget_usd = 0;
UPDATE tenants SET monthly_budget_usd = 5000.00 WHERE plan = 'enterprise' AND monthly_budget_usd = 0;

-- ---------------------------------------------------------------------------
-- tenant_api_keys: plan scoping + per-key budget (M7). A key can be tighter than its tenant
-- (e.g. a sandbox key capped at $5) but never looser. key_scope limits what the key can do.
-- ---------------------------------------------------------------------------
ALTER TABLE tenant_api_keys
    ADD COLUMN IF NOT EXISTS plan              TEXT    NOT NULL DEFAULT 'free',
    ADD COLUMN IF NOT EXISTS key_scope         TEXT    NOT NULL DEFAULT 'chat'
        CHECK (key_scope IN ('chat', 'ingest', 'admin')),
    ADD COLUMN IF NOT EXISTS monthly_budget_usd NUMERIC(10,2);

CREATE INDEX IF NOT EXISTS tenant_api_keys_tenant_active_idx
    ON tenant_api_keys (tenant_id) WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------------------
-- usage_events: the app's OWN metering record. LiteLLM under-counts streamed tokens by
-- 8-15% on client disconnect (it counts what it proxied, not what the model emitted); this
-- table is the server-side truth (real usage from the final streamed chunk when the provider
-- supports include_usage, else an estimated flag). The reconciliation DAG compares this
-- against LiteLLM_SpendLogs + Langfuse usage and alerts on >5% divergence.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_events (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         TEXT        NOT NULL,
    key_id            BIGINT      REFERENCES tenant_api_keys(id) ON DELETE SET NULL,
    request_id        TEXT        NOT NULL,         -- our trace/span id for join to Langfuse
    model             TEXT        NOT NULL,
    prompt_tokens     INTEGER     NOT NULL DEFAULT 0,
    completion_tokens INTEGER     NOT NULL DEFAULT 0,
    total_tokens      INTEGER     NOT NULL DEFAULT 0,
    cost_usd          NUMERIC(12,6) NOT NULL DEFAULT 0,
    estimated         BOOLEAN     NOT NULL DEFAULT FALSE,  -- TRUE when usage wasn't in the stream
    cached            BOOLEAN     NOT NULL DEFAULT FALSE,  -- cache hit (0 cost, still metered)
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS usage_events_tenant_month_idx
    ON usage_events (tenant_id, date_trunc('month', created_at));
CREATE INDEX IF NOT EXISTS usage_events_created_idx ON usage_events (created_at);

-- Per-tenant, per-month usage rollup for the admin dashboard + budget enforcement.
-- A view over usage_events (the app DB), distinct from tenant_spend_monthly which lives in
-- the LiteLLM DB and aggregates LiteLLM_SpendLogs.
CREATE OR REPLACE VIEW tenant_usage_monthly AS
SELECT
    date_trunc('month', created_at)              AS usage_month,
    tenant_id,
    COUNT(*)                                     AS request_count,
    SUM(prompt_tokens)                           AS prompt_tokens,
    SUM(completion_tokens)                       AS completion_tokens,
    SUM(total_tokens)                            AS total_tokens,
    SUM(cost_usd)                                AS cost_usd,
    AVG(CASE WHEN estimated THEN 1 ELSE 0 END)   AS estimated_frac
FROM usage_events
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
COMMENT ON VIEW tenant_usage_monthly IS
  'M7: per-tenant monthly usage from the app''s own metering (server-side truth for the LiteLLM under-count reconciliation).';

-- ---------------------------------------------------------------------------
-- sampled_evals: production traffic sampled at EVAL_SAMPLE_RATE (default 5%) gets a
-- lightweight faithfulness+answer-relevancy LLM-judge score. Scores also go to Langfuse
-- (Tracer.record_score) so they trend in the Grafana dashboard. Full RAGAS stays nightly
-- in eval-nightly.yml; this is the always-on production signal.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sampled_evals (
    id                 BIGSERIAL PRIMARY KEY,
    tenant_id          TEXT        NOT NULL,
    trace_id           TEXT,                       -- Langfuse trace id (nullable if tracing off)
    question           TEXT        NOT NULL,
    answer             TEXT        NOT NULL,
    contexts           JSONB       NOT NULL DEFAULT '[]'::jsonb,
    faithfulness       DOUBLE PRECISION,           -- 0..1, NULL if judge failed
    answer_relevancy   DOUBLE PRECISION,
    sampled_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    evaluated_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS sampled_evals_sampled_idx ON sampled_evals (sampled_at);
CREATE INDEX IF NOT EXISTS sampled_evals_tenant_idx ON sampled_evals (tenant_id, sampled_at);

-- ---------------------------------------------------------------------------
-- regression_alerts: the prod_eval_alerts DAG writes a row when the 7-day rolling
-- faithfulness drops below the prior 7-day window by more than the threshold, and POSTs to
-- Alertmanager. Persisted so Grafana can surface the alert history.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regression_alerts (
    id              BIGSERIAL PRIMARY KEY,
    metric          TEXT        NOT NULL,
    window_value    DOUBLE PRECISION NOT NULL,
    baseline_value  DOUBLE PRECISION NOT NULL,
    drop_pct        DOUBLE PRECISION NOT NULL,
    fired_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved        BOOLEAN     NOT NULL DEFAULT FALSE
);

-- ---------------------------------------------------------------------------
-- billing_ledger: append-only record of Lago sync events (customer created, subscription
-- activated, billable metric event sent, invoice finalized). The reconciliation source for
-- "what we told Lago vs what LiteLLM logged". Keep it simple: one row per Lago API call.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS billing_ledger (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT        NOT NULL,
    event_type      TEXT        NOT NULL,   -- customer_created|subscription|metric_event|invoice
    lago_id         TEXT,                    -- Lago's id for the object we synced
    payload         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT        NOT NULL DEFAULT 'sent',  -- sent|failed|replayed
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS billing_ledger_tenant_idx ON billing_ledger (tenant_id, created_at);