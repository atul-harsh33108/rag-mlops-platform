# RAG Knowledge-Base / Support-Assistant — MLOps Platform

A production-grade LLM **RAG** support-assistant (answer questions over a document corpus with citations) that is also a viable product — evolving from a local-first MVP into a billable multi-tenant SaaS. Built as 7 shippable milestones so each is independently demoable.

> **Status:** scaffolding — Milestone 1 (Local-First RAG MVP) in progress. See `docs/architecture.md` and the plan.

## What it is

Ask a question → retrieve grounded context from a vector DB → generate a cited answer, with every step **traced, costed, and evaluated**, and the corpus **automatically re-indexed** when it changes. The same stack runs on your laptop (Docker Compose + local K8s), on AWS EKS, and on any Kubernetes via one Helm chart.

## Stack (2026, version-pinned)

| Layer | Choice | Why |
|---|---|---|
| LLM serving | vLLM v0.25.x (prod) / Ollama v0.30.x (local) | OpenAI-compatible; swap via `base_url`. Qwen 3 14B (Apache 2.0, 128K). |
| Embeddings | BGE-M3 via Hugging Face TEI v1.9.x | dense+sparse+ColBERT in one model; ~1GB VRAM. |
| Vector DB | Qdrant v1.18.x | Rust single binary; TurboQuant; payload-based tenant RLS. |
| Retrieval | LangChain/LangGraph (`langchain-core`+`langchain-qdrant`) + BGE-reranker-v2-m3 | hybrid dense+BM25, cross-encoder rerank. |
| Tracking/registry | MLflow 3.14.x | Tracking + Model Registry + Prompt Registry. |
| LLM gateway | LiteLLM proxy | unified routing, fallbacks, budgets, per-tenant spend (→ Lago→Stripe at M7). |
| Orchestration | Airflow 3.x | DAGs with Dataset triggers for corpus-change re-indexing. |
| Feature store | **Feast deferred** | ceremony for pure RAG; revisit if classical-ML features added. |
| Evals/observability | Langfuse v3.213 + OpenLLMetry v0.62 + RAGAS v0.4 + DeepEval | traces + cost + RAGAS scores; CI gate on faithfulness. |
| UI | Open WebUI (demo) → Next.js 16 + Vercel AI SDK (customer-facing) | citations, streaming, tenant switcher. |
| Auth | Clerk (demo) / Keycloak (self-hosted) | per-tenant; Qdrant RLS via server-built filters. |
| Infra | Docker Compose → k3d/kind → AWS EKS (Terraform) → cloud-agnostic Helm + Argo CD | one chart, three environments. |

## Quickstart (Milestone 1, local)

```bash
cp .env.example .env              # fill in CHANGE_ME secrets
task dev:up core,ai               # Qdrant, TEI, Ollama, Redis, app, Open WebUI
task seed                         # load ~500 support_faq + product_docs into Qdrant
# API:
curl -N http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -d '{"question":"How do I reset my password?","tenant":"acme"}'
# UI:   http://127.0.0.1:3000      (Open WebUI, pointed at Ollama)
# Docs: http://127.0.0.1:8000/docs
```

## Windows / WSL2 prerequisites

See `docs/runbooks/local.md`. Short version: Docker Desktop + WSL2 Ubuntu 24.04, repo on `~/mlops` (ext4, **not** `/mnt/c` — 3–5x slower), NVIDIA Windows driver 560+ (never install cuda meta-packages inside WSL), `.wslconfig` with `memory=24GB sparseVhd=true`. `.gitattributes` enforces LF so Helm/shell don't break under CRLF.

## Milestones

| # | Ship | ~Days |
|---|---|---|
| 0 | Repo skeleton + WSL2 prereqs | 0.5 |
| 1 | Local RAG MVP (Compose + Ollama + Qdrant + TEI + LangChain + Open WebUI) | 3–4 |
| 2 | Langfuse + OpenLLMetry + RAGAS/DeepEval + MLflow + semantic cache | 4–5 |
| 3 | Airflow ingestion + LiteLLM gateway + full hybrid retrieval + corpus-versioning | 5–6 |
| 4 | k3d/kind + Helm umbrella + Argo CD + CI/CD (lint/scan/sign/sbom) | 5–6 |
| 5 | AWS EKS + Terraform + Karpenter + Bedrock/vLLM Bifrost + Grafana alerts | 7–9 |
| 6 | Cloud-agnostic values + Next.js UI + Clerk auth + Qdrant RLS + rate limits | 4–5 |
| 7 | SaaS billing (LiteLLM→Lago→Stripe) + prod-sampled evals + 7-day alerts | 5–6 |

Total ~34–42 ideal days (solo), ~8–10 weeks part-time. Each milestone demoable standalone.

## Layout

See `docs/architecture.md` for the monorepo tree and data flow. Key files:
- `docker/compose*.yml` — the local-first stack every milestone builds on.
- `app/src/app/rag/retriever.py` — LangChain hybrid retrieval + BGE-reranker (product quality core).
- `app/src/app/qdrant/filter_builder.py` — server-side RLS filter from JWT (security-critical).
- `helm/mlops-platform/Chart.yaml` — umbrella chart deploying everywhere.
- `evals/deepeval/test_rag_gate.py` — the eval gate that makes this eval-driven, not vibe-driven.
- `pipelines/dags/reindex_on_change.py` — corpus-version bump + cache invalidation.

## License

TBD (project code). Demo dataset `tarekmasryo/rag-qa-logs-corpus-data` is CC BY 4.0.