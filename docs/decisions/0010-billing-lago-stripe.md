# ADR 0010 — Billing: LiteLLM -> Lago -> Stripe

**Status:** Accepted

## Decision

Meter per-tenant LLM spend through **LiteLLM** (`LiteLLM_SpendLogs`), aggregate it in the
`tenant_spend_monthly` view, report it to **Lago** as a billable metric via LiteLLM's native
`lago` success_callback, and let **Lago** invoice through **Stripe**. The app manages the
billing *lifecycle* (Lago customer + subscription on upgrade; Stripe webhook updates plan +
budget); LiteLLM manages the *metering* (one billable-metric event per call).

## Rationale

- **No native LiteLLM→Stripe path.** LiteLLM logs spend and can cap budgets, but it has no
  direct Stripe callback. Lago is the open-source billing layer purpose-built to sit between
  a metering source and Stripe: it owns customers, subscriptions, billable metrics, and
  invoice generation. This is the documented LiteLLM billing path.
- **Separation of meter vs. invoice.** LiteLLM is good at per-request metering (it sees every
  call, computes cost per model). It is bad at subscription cycles, proration, dunning. Lago
  is the inverse. Splitting them lets each do its job; the `billable_metric` `llm-spend`
  (units = USD) is the contract between them.
- **Plan = tenant, not key.** The plan lives on the tenant (the Clerk org). Keys inherit the
  tenant plan; a key may carry a *tighter* budget but the rate limit always follows the tenant,
  so a tenant can't mint many keys to evade limits. The Stripe webhook is the single source of
  truth for plan changes; the Clerk webhook only provisions the tenant row.
- **Hard cap at two layers.** The app checks the cap *before* generation (`spend.py`) and
  returns a 429 with an upgrade prompt — fast, user-friendly. LiteLLM's `budget_ratelimiter`
  is the defense-in-depth backstop at the gateway (catches anything that bypasses the app).
- **Lago API pinned.** `lago.py` targets a fixed Lago REST shape and sends `X-Lago-Version`.
  Reconciliation (ADR 0011) closes the gap between what LiteLLM logged and what Lago invoiced.

## Consequences

- **Two DBs to reconcile.** `LiteLLM_SpendLogs` lives in the LiteLLM DB; `usage_events` (app's
  server-side truth) lives in the app DB. The `usage_reconciliation` DAG compares them daily
  and alerts on >5% divergence (ADR 0011).
- **Streaming under-counting.** LiteLLM under-counts streamed tokens on client disconnect
  (8-15%). The app records real usage server-side; reconciliation surfaces the gap so a
  backfill billable-metric event can be sent to Lago before invoicing.
- **Rounding consistency.** Spend → `billable_metric` `units` must round the same way LiteLLM
  logs it (6 decimals) or invoices drift from logs. The reconciliation DAG is the guard.
- **Stripe customer metadata.** The Stripe Customer carries `metadata.tenant_id` and the
  Subscription carries `metadata.plan`; the webhook reads these to map back to the tenant.
  Setting them at checkout is a runbook step.
- **Out of scope (deferred):** cross-tenant platform-admin revenue views; usage-based *tiered*
  pricing (flat plan budgets now, true per-token tiers later); Stripe billing portal link
  (stub in the admin UI, full portal wiring later).

## Revisit trigger

Re-evaluate if (a) we want pure per-token tiered pricing without plan budgets (move more logic
into Lago's tiered billable metrics), or (b) Lago's API shape changes and the pinned client
diverges, or (c) we outgrow Lago and need Stripe Billing directly (drop Lago, write a LiteLLM
callback that creates Stripe Usage Records).