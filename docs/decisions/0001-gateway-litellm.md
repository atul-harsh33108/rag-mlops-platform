# ADR 0001 — LiteLLM proxy as the unified LLM gateway

**Status:** Accepted

## Context

Two candidate gateways in 2026: **MLflow 3.14 AI Gateway** (now integrated into the tracking server) and **LiteLLM proxy**. Both route 100+ providers onto the OpenAI schema, support fallbacks, budgets, OTel. The later SaaS milestone (M7) needs per-tenant usage metering and a billing path to Stripe.

## Decision

Use **LiteLLM proxy** as the gateway. Keep **MLflow** for Tracking, Model Registry, and Prompt Registry only.

## Rationale

- M7 billing needs LiteLLM's built-in `callbacks:["lago"]` → Lago → Stripe, and the `LiteLLM_SpendLogs` Postgres table keyed by API key/model/tenant. MLflow AI Gateway has no native Lago/Stripe path → would force a second gateway or a custom billing callback.
- LiteLLM gives mature per-key spend tracking, budgets, and the Bifrost Cascade (vLLM primary, Bedrock fallback) falls out of its router config for free (M5).
- MLflow AI Gateway's strengths (guardrails, prompt routing, OTel) overlap with what Langfuse + the app already provide; adopting it would duplicate the gateway without removing the billing gap.

## Consequences

- M3 adds LiteLLM; M7 Lago → Stripe works with zero new gateway code.
- **Known bug:** OpenLLMetry-on-LiteLLM breaks for non-OpenAI providers (issue #3167). Use LiteLLM's **native `otel` callback** instead; ship OTel from LiteLLM directly to the collector.