# Runbook — SaaS multi-tenant billing + production evals (M7)

M7 turns the RAG platform into a billable SaaS: per-tenant API keys with plan-scoped rate
limits + monthly budgets, LiteLLM→Lago→Stripe metered billing, a fix for LiteLLM streaming
under-counting, and production-sampled evals with a 7-day regression alert. Assumes M5 (EKS)
or M4 (local K8s) is up.

## Architecture (one paragraph)

Each `/chat` turn: resolve tenant (JWT/API key) → cache lookup (free) → **hard-budget check**
(`spend.py`, 429 + upgrade prompt if over cap) → retrieve → generate, sending
`metadata.tenant_id` to LiteLLM (so `LiteLLM_SpendLogs` groups by tenant) and
`stream_options.include_usage` (so we capture the **real** token usage) → meter the real usage
to `usage_events` (server-side truth) → maybe sample 5% for a lightweight judge eval → Langfuse
score. Nightly: `usage_reconciliation` DAG compares `usage_events` vs `LiteLLM_SpendLogs`
(>5% divergence → Alertmanager + `regression_alerts`); `prod_eval_alerts` DAG rolls 7-day
faithfulness vs prior 7-day (>10% relative drop → Alertmanager). LiteLLM's `lago` callback
reports spend to Lago; Lago invoices via Stripe; the Stripe webhook updates the tenant plan.

## 1. Plans + budgets

Plans are defined in `app/src/app/billing/plans.py`:

| Plan | rate/min | monthly budget | Models |
|---|---|---|---|
| free | 20 | $50 | qwen3:14b |
| pro | 120 | $500 | qwen3:14b, judge |
| enterprise | 600 | $5000 | any |

The plan lives on the **tenant** (`tenants.plan`); keys inherit it. A key may carry a tighter
`monthly_budget_usd` (sandbox key) but the rate limit always follows the tenant. Override
budgets per tenant in SQL: `UPDATE tenants SET monthly_budget_usd=750, budget_hard_pct=90 WHERE id='acme';`
(`budget_hard_pct` lets you cap below 100% — e.g. alert at 90% of budget).

## 2. Lago setup (out-of-band, once)

Lago self-hosts (or use Lago Cloud). In the Lago UI/API:

1. Create three **plans** with codes `free`, `pro`, `enterprise` (matching
   `PLAN_TO_LAGO_CODE` in `lago.py`).
2. Create a **billable metric** with code `llm-spend` (units = USD; aggregation = sum).
3. Attach that billable metric to each plan (pro/enterprise charge per unit; free = $0).
4. Set the LiteLLM env via External Secrets: `LAGO_API_BASE_URL`, `LAGO_API_KEY`,
   `LAGO_WEBHOOK_HOST`. LiteLLM's `lago` callback (enabled in `config.eks.yaml`) then reports
   each call's spend as an `llm-spend` event for the tenant's external_customer_id.

When a tenant upgrades (Stripe checkout), the app creates the Lago customer + subscription
(`billing.lago.ensure_customer` / `create_subscription`), recorded in `billing_ledger`.

## 3. Stripe setup (out-of-band, once)

1. Create products + prices for the three plans; note the price IDs.
2. Create a **Stripe webhook** endpoint pointing at `https://api.example.com/webhooks/stripe`
   subscribing to `customer.subscription.*` + `invoice.paid`. Put the signing secret in
   `STRIPE_WEBHOOK_SECRET` (External Secret).
3. At checkout, set **Customer metadata** `tenant_id=<tenant>` and **Subscription metadata**
   `plan=<free|pro|enterprise>` — the webhook reads these to map back to the tenant.
4. Set `STRIPE_SECRET_KEY` (External Secret).

The webhook (`/webhooks/stripe`) updates `tenants.plan` + `monthly_budget_usd` on
`subscription.updated` (active→plan, otherwise→free) and drops to `free` on
`subscription.deleted`.

## 4. Clerk org → tenant sync

Create a Clerk webhook for `organization.*` → `https://api.example.com/webhooks/clerk`; put
the signing secret in `CLERK_WEBHOOK_SECRET`. New orgs auto-create a `free` tenant row
(`tenants.id = org.id` = Qdrant `group_id`). `organization.deleted` revokes all the tenant's
API keys (keeps billing/usage history). Install `svix` in the app image
(`uv add svix` — guarded import, so the app boots without it, but the webhook 503s until
installed).

## 5. Env vars (M7)

```
# Lago
LAGO_API_BASE_URL=https://api.lago.dev/api/v1
LAGO_API_KEY=...
LAGO_WEBHOOK_HOST=https://api.example.com
# Stripe
STRIPE_SECRET_KEY=sk_...
STRIPE_WEBHOOK_SECRET=whsec_...
# Clerk webhook
CLERK_WEBHOOK_SECRET=whsec_...
# Sampled eval
EVAL_SAMPLE_RATE=0.05
JUDGE_MODEL=judge          # LiteLLM routes "judge" → Bedrock Claude (EKS) / Ollama (local)
```

Add `svix` and `stripe` to the app image (`app/pyproject.toml` when wiring prod; guarded
imports keep local dev/tests working without them).

## 6. Verify the billing loop (local)

```bash
# Seed a tenant over cap to see the 429 + upgrade prompt:
docker exec -i postgres psql -U mlops -d mlops -c "UPDATE tenants SET monthly_budget_usd=0.01 WHERE id='acme';"
curl -N http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -d '{"question":"How do I reset my password?","tenant":"acme","stream":false}'
# -> HTTP 429 {"detail":"monthly budget exceeded","plan":"pro","upgrade":"Upgrade your plan..."}

# Reset + generate traffic, then check usage + forecast:
docker exec -i postgres psql -U mlops -d mlops -c "UPDATE tenants SET monthly_budget_usd=500 WHERE id='acme';"
# (issue a key, call /chat a few times with the key)
curl http://127.0.0.1:8000/admin/plan   -H "Authorization: Bearer <jwt>"
curl http://127.0.0.1:8000/admin/usage  -H "Authorization: Bearer <jwt>"
curl http://127.0.0.1:8000/admin/usage/forecast -H "Authorization: Bearer <jwt>"
```

UI: sign in → `/admin` shows plan, spend bar, forecast, per-model usage table.

## 7. Verify sampled eval + alerts

```bash
# Force sampling (set EVAL_SAMPLE_RATE=1.0 temporarily) + generate a few turns, then:
docker exec -i postgres psql -U mlops -d mlops -c "SELECT tenant_id, faithfulness, answer_relevancy, sampled_at FROM sampled_evals ORDER BY sampled_at DESC LIMIT 5;"
# Langfuse: the trace shows faithfulness + answer_relevancy scores.

# Trigger the Airflow DAGs manually:
airflow dags trigger usage_reconciliation
airflow dags trigger prod_eval_alerts
# regression_alerts rows + Alertmanager alerts on divergence / faithfulness drop.
docker exec -i postgres psql -U mlops -d mlops -c "SELECT metric, window_value, baseline_value, drop_pct, fired_at FROM regression_alerts ORDER BY fired_at DESC LIMIT 5;"
```

## 8. Gotchas

- **`svix` / `stripe` are optional.** Guarded imports — the app boots without them, but the
  webhooks return 503 until installed and the signing secret is set. Don't run prod without.
- **Streaming under-count is real.** LiteLLM logs ~8-15% low on client disconnects;
  `usage_events` is the truth. If a tenant disputes an invoice, reconcile against
  `usage_events`, not `LiteLLM_SpendLogs`.
- **`estimated_frac` should be ~0 in prod.** vLLM/Bedrock via LiteLLM return usage; only
  direct-Ollama (local) estimates. A rising `estimated_frac` in prod means a provider stopped
  returning `usage` — investigate.
- **Plan follows the tenant, not the key.** Minting keys doesn't raise the rate limit. A key
  can only be *tighter* than its tenant.
- **Reconciliation is daily.** It protects monthly invoices, not real-time spend. The
  real-time cap is `spend.py` (pre-generation). Don't rely on LiteLLM's budget backstop alone.
- **Cross-tenant platform-admin views are deferred.** `/admin/*` is tenant-scoped (a tenant
  sees only itself). A platform-admin revenue dashboard across all tenants is a follow-up
  (needs a separate platform-admin role + new endpoints).