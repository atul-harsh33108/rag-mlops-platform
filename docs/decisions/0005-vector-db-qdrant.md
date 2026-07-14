# ADR 0005 — Qdrant over Milvus

**Status:** Accepted

## Decision

Use **Qdrant v1.18.x** as the vector DB for the support-assistant RAG corpus (expected 1–50M chunks).

## Rationale

- Single Rust binary, no external deps (etcd/MinIO/Pulsar) → simpler local + Helm deploy than Milvus's microservices.
- One-stage payload filtering prunes during HNSW traversal → 2–4x faster on high-selectivity filters (we filter by `group_id` tenant on every query).
- TurboQuant TQ4 (8x compression at scalar-quant recall), binary quantization.
- Native multi-tenancy: payload `group_id` + `is_tenant:true` index (v1.11+); tiered multitenancy (v1.16+).
- Qdrant Edge embedded mode → fast unit tests.

## Revisit trigger

Switch to **Milvus** only if the corpus crosses ~100M vectors or we need Milvus Operator-grade K8s topology / GPU-accelerated index building. On AWS, **OpenSearch Serverless NextGen** (scale-to-zero, GA May 2026) is the documented alternative only for managed hybrid search / FedRAMP-HIPAA.