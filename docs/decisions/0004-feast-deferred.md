# ADR 0004 — Feast feature/context store deferred

**Status:** Accepted (deferred)

## Context

The original requested stack included Feast. 2026 research finds Feast is **largely ceremony for a pure RAG project**: its core value props (point-in-time correctness, online/offline consistency, low-latency tabular feature serving) solve problems a RAG system doesn't have. The maintainer-disputed "context engine" rebrand (GitHub issue #5761) is not yet shipped as a differentiated product.

## Decision

**Do not install Feast.** Use:
- **Qdrant** for retrieval context,
- **Langfuse / Postgres** for conversational memory (session/trace storage),
- **Redis** for hot session state.

Document this ADR as the trigger to revisit.

## Revisit trigger

Reinstall Feast **only when** the platform adds classical-ML features that need point-in-time joins alongside RAG context (e.g. a churn/propensity model that joins user historical features to a support prediction). Watch feast-dev/feast#5761 — if Feast 2.0 ships a genuine unified `get_context(entity_id)` API with latency targets, reassess.

## Consequences

- One fewer stateful service in the stack (lower ops cost, simpler Helm umbrella).
- No point-in-time feature correctness — acceptable because RAG retrieval is vector + metadata filtering, not event-timestamp feature joins.