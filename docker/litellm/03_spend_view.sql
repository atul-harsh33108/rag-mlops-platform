-- tenant_spend_monthly view over LiteLLM_SpendLogs (M3 foundation, M7 billing).
--
-- LiteLLM creates the "LiteLLM_SpendLogs" table in the `litellm` DB on first boot. This
-- view aggregates per-tenant, per-month spend — the input to Lago billable metrics and
-- the Grafana "cost per turn" panel. Apply AFTER LiteLLM has bootstrapped its schema:
--
--     task spend:view
--
-- (runs psql against the litellm DB). CREATE OR REPLACE VIEW is idempotent once the
-- base table exists. The `model_group` column carries the tenant via LiteLLM's
-- `metadata.tenant_id` (set by the app as `user`/metadata on each /chat call — wired M7).
--
-- NOTE: LiteLLM stores spend metadata in the `metadata` JSONB column. Tenant id is
-- recorded under metadata->>'tenant_id'. Adjust the key if the app sets it elsewhere.

CREATE OR REPLACE VIEW tenant_spend_monthly AS
SELECT
    date_trunc('month', "startTime")               AS spend_month,
    COALESCE(metadata->>'tenant_id', 'unknown')     AS tenant_id,
    COALESCE("model_group", model)                  AS model,
    COUNT(*)                                        AS request_count,
    SUM("total_tokens")                             AS total_tokens,
    SUM(prompt_tokens)                             AS prompt_tokens,
    SUM(completion_tokens)                          AS completion_tokens,
    SUM("spend")                                    AS spend_usd
FROM "LiteLLM_SpendLogs"
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 2;

COMMENT ON VIEW tenant_spend_monthly IS
  'M3 foundation for M7 billing: per-tenant monthly LLM spend from LiteLLM_SpendLogs.';