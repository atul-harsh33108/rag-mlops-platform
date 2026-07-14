# RAG Knowledge-Base / Support-Assistant — MLOps Platform

A production-grade, **viable-product** LLM **RAG** support-assistant: ask a question → retrieve grounded context from a vector DB → generate a cited answer — with every step **traced, costed, and evaluated**, the corpus **automatically re-indexed** when it changes, and the whole thing billable as a **multi-tenant SaaS**.

Built as **7 shippable milestones**, each independently demoable, each layering on the last:

> local Docker Compose MVP → observability + evals → orchestration + gateway → local K8s + Helm + GitOps → AWS EKS → cloud-agnostic Helm + customer UI → SaaS billing + production-sampled evals.

> **Status:** all 7 milestones (M0–M7) complete. See [docs/architecture.md](docs/architecture.md) for the design and [docs/runbooks/](docs/runbooks/) for operating it.

---

## What it is

Ask a question → retrieve grounded context from a vector DB → generate a cited answer, with every step **traced, costed, and evaluated**, and the corpus **automatically re-indexed** when it changes. The same stack runs on your laptop (Docker Compose + local K8s), on AWS EKS, and on any Kubernetes via one Helm chart — and ships as a billable multi-tenant API with per-tenant rate limits, usage metering, Lago→Stripe billing, and continuous production-sampled evaluation with 7-day regression alerts.

### Data flow (one `/chat` turn)

```
Client ──/chat (JWT or API key)──▶ FastAPI
  │  resolve tenant from auth (never from a client-supplied filter)
  │  per-plan rate limit (slowapi + Redis)
  │  hard budget cap (assert_under_budget → 429 + upgrade prompt if over)
  │  semantic cache hit? ──yes──▶ return cached answer (metered 0-cost)
  ▼  no
  Qdrant hybrid search (dense BGE-M3 + sparse BM25), filter group_id==tenant  ◀── RLS enforced server-side
  │  BGE-reranker-v2-m3 cross-encoder rerank (top-50 → top-8)
  ▼
  Build prompt (system prompt from MLflow Prompt Registry alias `production`)
  │  stream LLM via LiteLLM gateway (Bifrost: vLLM primary → Bedrock fallback)
  │  stream_options.include_usage → real token count on final chunk
  ▼
  SSE stream tokens + citation chips to client
  │  record usage_events (server-side truth for billing reconciliation)
  │  maybe_sample_and_eval (5% Bernoulli → LLM-judge faithfulness/relevancy → Langfuse)
  ▼
  Cache full answer; every span traced to Langfuse + costed via LiteLLM SpendLogs → Lago → Stripe
```

---

## Stack (version-pinned, 2026)

| Layer | Choice | Why |
|---|---|---|
| LLM serving | vLLM v0.10.x (prod) / Ollama v0.30.x (local) | OpenAI-compatible; swap via `base_url`. Qwen 3 14B (Apache 2.0, 128K ctx). |
| Embeddings | BGE-M3 via Hugging Face TEI v1.9.x | dense + sparse + ColBERT in one model; ~1GB VRAM. |
| Vector DB | Qdrant v1.18.x | Rust single binary; TurboQuant; payload-based tenant RLS (`group_id`). |
| Retrieval | LangChain (`langchain-core` + `langchain-qdrant`) + BGE-reranker-v2-m3 | hybrid dense + BM25 (RRF fusion), cross-encoder rerank. |
| Tracking / registry | MLflow 3.14.x | Tracking + Model Registry + **Prompt Registry** (load system prompt by alias `production`). |
| LLM gateway | LiteLLM proxy | unified routing, Bifrost fallbacks, budgets, per-tenant spend, `lago` + `otel` callbacks. |
| Orchestration | Airflow 3.x (`airflow.sdk`) | DAGs with Assets triggers for corpus-change re-indexing; usage reconciliation + eval alerts. |
| Feature store | **Feast deferred** | ceremony for pure RAG; revisit if classical-ML features needing point-in-time joins are added. |
| Evals / observability | Langfuse v3.213 + OpenLLMetry v0.62 + RAGAS v0.4 + DeepEval | traces + cost + RAGAS scores; CI gate on faithfulness ≥ 0.80. |
| UI | Open WebUI (internal demo) → Next.js 16 + Vercel AI SDK 7 + React 19 (customer-facing) | SSE streaming, citation chips, source pane, tenant switcher, /keys + /admin. |
| Auth | Clerk (demo, Organizations = tenants) / Keycloak (self-host, one realm per tenant) | fail-closed JWT verify; Qdrant RLS via server-built filters. |
| Billing | LiteLLM SpendLogs → `usage_events` (reconciliation source of truth) → **Lago → Stripe** | per-tenant API keys, plan tiers, hard budget cap → 429 + upgrade prompt. |
| Infra | Docker Compose → k3d/kind → AWS EKS (Terraform, Karpenter, IRSA) → cloud-agnostic Helm + Argo CD | one chart, three environments; no static AWS keys (OIDC/IRSA). |

---

## Quickstart

### Local-first MVP (M1)

```bash
cp .env.example .env              # fill in CHANGE_ME secrets
task dev:up core,ai               # Qdrant, TEI, Ollama, Redis, app, Open WebUI
task seed                         # load ~500 support_faq + product_docs into Qdrant
# API:
curl -N http://127.0.0.1:8000/chat -H 'Content-Type: application/json' \
  -d '{"question":"How do I reset my password?","tenant":"acme"}'
# UI:    http://127.0.0.1:3000     (Open WebUI, pointed at Ollama)
# Docs:  http://127.0.0.1:8000/docs
```

### Full stack (gateway + observability + orchestration)

```bash
task dev:up core,ai,gateway,mlops,orchestration
# Langfuse  http://127.0.0.1:3001    MLflow  http://127.0.0.1:5000
# LiteLLM   http://127.0.0.1:4000    Airflow http://127.0.0.1:8080
task prompt:register            # register RAG system prompt + set `production` alias
task ingest:full                # trigger Airflow ingest → chunk → embed → index DAG
task spend:monthly               # per-tenant monthly spend from LiteLLM_SpendLogs
```

### Local Kubernetes (k3d + Helm + Argo CD)

```bash
task k3d:up                     # create cluster + in-cluster registry
task k3d:load                   # build + side-load app image
task helm:install               # helm upgrade --install -f values-kind.yaml
task argocd:apps                # apply Argo CD Applications (set <GIT_REPO_URL> first)
task argocd:wait                # argocd app wait mlops-dev --sync --health
```

### AWS EKS (M5)

```bash
task terraform:apply prod       # vpc + eks + Karpenter + RDS + ECR + IRSA + Grafana dashboards
task argocd:sync prod           # Argo syncs the chart with values-eks.yaml
# External Secrets + IRSA inject DATABASE_URL / Clerk / Lago / Stripe keys — no static creds.
```

### Cloud-agnostic (any K8s — GKE / AKS / OpenShift)

```bash
helm install mlops ./helm/mlops-platform -f helm/mlops-platform/values-generic.yaml -n mlops --create-namespace
```

See [docs/runbooks/local.md](docs/runbooks/local.md), [docs/runbooks/eks.md](docs/runbooks/eks.md), and [docs/runbooks/saas.md](docs/runbooks/saas.md) for full operating procedures, drills, and troubleshooting.

---

## Windows / WSL2 prerequisites

Docker Desktop (WSL2 backend) + WSL2 Ubuntu 24.04. **Keep the repo on `~/mlops` (ext4), not `/mnt/c`** — 3–5× slower I/O on the mounted drive. NVIDIA **Windows** driver 560+ (never install cuda meta-packages inside WSL). `.wslconfig` with `memory=24GB sparseVhd=true`. `.gitattributes` enforces LF so Helm templates and shell scripts don't break under CRLF. See [docs/runbooks/local.md](docs/runbooks/local.md).

---

## Milestones

| # | Ships | Status |
|---|---|---|
| 0 | Repo skeleton + WSL2 prereq docs | ✅ |
| 1 | Local RAG MVP — Compose + Ollama + Qdrant + TEI + LangChain hybrid retrieval + Open WebUI | ✅ |
| 2 | Langfuse + OpenLLMetry + RAGAS/DeepEval + MLflow Prompt Registry + Redis semantic cache | ✅ |
| 3 | Airflow ingestion + LiteLLM gateway + full hybrid retrieval + corpus-versioning | ✅ |
| 4 | k3d/kind + Helm umbrella + Argo CD + CI/CD (lint/test/scan/sign/SBOM) | ✅ |
| 5 | AWS EKS + Terraform + Karpenter + Bedrock/vLLM Bifrost + Grafana 6-panel + alerts | ✅ |
| 6 | Cloud-agnostic Helm + Next.js UI + Clerk auth + Qdrant RLS + per-tenant rate limits | ✅ |
| 7 | SaaS billing (LiteLLM→Lago→Stripe) + prod-sampled 5% evals + 7-day regression alerts | ✅ |

Each milestone is demoable standalone. Total ~34–42 ideal days solo, ~8–10 weeks part-time.

---

## Repository layout

```
mlops/
├── app/                          # FastAPI RAG service (uv-managed, pydantic v2)
│   ├── src/app/
│   │   ├── api/                   #   chat, health, ingest, keys, admin, webhooks
│   │   ├── rag/                   #   retriever (hybrid+rerank), prompt_loader (MLflow alias)
│   │   ├── clients/               #   llm (include_usage capture), embeddings
│   │   ├── qdrant/                 #   client, filter_builder (RLS — security-critical)
│   │   ├── cache/                  #   semantic_cache (Redis, corpus-version keyed)
│   │   ├── auth/                   #   clerk (JWT), apikey (sha256 lookup), fail-closed
│   │   ├── billing/               #   plans, spend (hard cap), meter, lago
│   │   ├── evals/                  #   sampled (5% prod eval)
│   │   ├── observability/          #   otel, tracer, logging
│   │   └── scripts/               #   seed, register_prompt
│   └── tests/                     #   25 tests (RLS, billing, sampled, routes, health)
├── pipelines/                     # Airflow 3.x DAGs
│   └── dags/                      #   ingest, chunk_embed_index, reindex_on_change,
│                                  #   evals, usage_reconciliation, prod_eval_alerts
├── evals/                         # golden_dataset.jsonl, DeepEval gate, RAGAS runner, thresholds
├── ui/                            # Next.js 16 + AI SDK 7 + Clerk 7 + Tailwind v4 (customer UI)
├── helm/mlops-platform/           # umbrella chart + charts/{app,ui} subcharts + values-{kind,eks,generic}
├── infra/
│   ├── terraform/                 # modules/{vpc,eks,ecr,rds,s3-bucket,irsa,grafana-dashboards}, envs/{dev,prod}
│   └── k8s-bootstrap/             # Argo CD AppProject + Applications
├── docker/                        # compose.{core,ai,gateway,mlops,orchestration,observability,ui}.yml
│                                  # Dockerfile.{app,pipelines,ui}, litellm/clickhouse/postgres/otel configs
├── docs/                          # architecture.md, decisions/ (11 ADRs), runbooks/{local,eks,saas}.md, demo-script.md
├── .github/workflows/             # ci, deploy, eval-pr, eval-nightly
├── Taskfile.yml                   # entrypoint for the whole platform
└── .env.example
```

### Critical files

- `app/src/app/rag/retriever.py` — LangChain hybrid retrieval + BGE-reranker; the heart of product quality.
- `app/src/app/qdrant/filter_builder.py` — server-side RLS filter from JWT claims; the single security-critical point of tenant isolation.
- `app/src/app/billing/spend.py` — hard budget cap (`assert_under_budget` → `BudgetExceeded` → 429).
- `app/src/app/evals/sampled.py` — production-sampled eval (5% Bernoulli, fire-and-forget, never breaks `/chat`).
- `helm/mlops-platform/Chart.yaml` — the umbrella chart that deploys the stack everywhere.
- `evals/deepeval/test_rag_gate.py` — the eval gate that makes this eval-driven, not vibe-driven.
- `pipelines/dags/reindex_on_change.py` — corpus-version bump + cache invalidation correctness.
- `infra/terraform/modules/eks/` — EKS + Karpenter + add-ons + IRSA (no static AWS keys).

---

## Key features

**Retrieval quality.** Hybrid dense (BGE-M3) + sparse (BM25 via Qdrant sparse vectors) with RRF fusion, then BGE-reranker-v2-m3 cross-encoder rerank (top-50 → top-8). Pipeline config versioned and loaded from the MLflow Prompt Registry by alias `production`.

**Tenant isolation (security-critical).** Qdrant row-level security via payload `group_id` — **clients never supply filters**; the server builds `Filter(must=[group_id == tenant])` from the JWT/API-key. Every search path is unit-tested to carry the filter (`tests/test_filter_builder.py`, `tests/test_retriever_rls.py`); a missing filter is a CI security bug.

**Observability.** Every LLM/retrieval call traced to Langfuse (via OpenLLMetry/OTel; LiteLLM uses its native `otel` callback to avoid the non-OpenAI bug #3167) with cost + RAGAS scores. MLflow tracks experiments + model/prompt registry. Grafana 6-panel dashboard (request/error rate · p50/p95 latency · cost per turn · slowest traces · top errors) with PrometheusRule alerts (p95 > 8s, error > 5%, "no info" > 25%, spend > $2/h).

**Eval-driven.** DeepEval pytest gate on faithfulness ≥ 0.80 in CI (`eval-pr.yml`); full RAGAS suite nightly (`eval-nightly.yml`); **production-sampled eval** on 5% of live traffic (lightweight LLM-judge faithfulness + answer relevancy → Langfuse scores + `sampled_evals` table), with a 7-day rolling regression alert (`prod_eval_alerts` DAG, > 10% relative drop → Alertmanager).

**Orchestration.** Airflow 3.x DAGs: ingest → chunk → embed → index → eval; `reindex_on_change` senses corpus changes via Assets triggers and bumps `corpus_version` under a Postgres advisory lock (only after the Qdrant collection swap is verified healthy). Semantic cache keys include `corpus_version` so reindex invalidates correctly.

**Billing & metering.** Per-tenant API keys (hashed, plan-scoped). Plan tiers — **free** (20/min, $50), **pro** (120/min, $500), **enterprise** (600/min, $5000). Plan follows the tenant (not the key) so minting keys can't evade limits; a key's budget can only be tighter. **Two-layer hard cap**: app pre-generation 429 + upgrade prompt (fast) + LiteLLM `budget_ratelimiter:redis` backstop. Server-side `usage_events` is the reconciliation source of truth (fixes LiteLLM's 8–15% stream under-count on client disconnect — ADR 0011); a daily DAG reconciles against LiteLLM SpendLogs and alerts on > 5% divergence. Spend flows LiteLLM → Lago (billable metric `llm-spend`) → Stripe. Clerk org → tenant sync via svix-verified webhook; Stripe subscription → plan + budget via Stripe-signed webhook.

**Resilience.** Bifrost cascade: vLLM primary → Bedrock fallback on Spot interruption (LiteLLM fallback chain + AWS Node Termination Handler drains in-flight). vLLM reads weights from S3 via Mountpoint CSI (ReadOnlyMany PV, ~95% cheaper than EBS; ADR 0009). Qdrant 3-node Raft for HA.

---

## Testing & CI

```bash
# App
cd app && uv sync && uv run pytest -q          # 25 tests
uv run ruff check src tests && uv run ruff format --check src tests

# Evals gate
cd evals && uv run pytest deepeval --fail-on-threshold-breach

# DAGs
ruff check pipelines/dags
```

CI (`.github/workflows/`):
- **ci.yml** (PRs): uv lock/ruff/pytest → build images → Trivy (SARIF, fail HIGH/CRITICAL) → cosign sign + syft SBOM → push GHCR (main only) → gitleaks. **No deploy from PRs.**
- **eval-pr.yml**: DeepEval faithfulness gate + RAGAS faithfulness/relevance as PR comment.
- **eval-nightly.yml**: full RAGAS suite on the golden set.
- **deploy.yml** (main): digest-pin the image in `values-eks.yaml` via `yq` (ECR `batch-get-image` → `repo@sha256:`) → Argo CD sync → `kubectl rollout status` → smoke test (fixed canary question, assert answer + citation) → manual approval to promote.

---

## Architecture decisions (ADRs)

See [docs/decisions/](docs/decisions/README.md):

1. LiteLLM as the unified LLM gateway (not MLflow AI Gateway — no native billing path)
2. Airflow as orchestrator
3. LangChain for retrieval (`langchain-core` + `langchain-qdrant`, not deprecated `langchain-community`)
4. Feast deferred
5. Qdrant as vector DB
6. Clerk (demo) / Keycloak (self-host) for auth
7. Airflow 3.x (`airflow.sdk`, Assets not Datasets)
8. Bifrost: vLLM primary → Bedrock fallback
9. S3 + Mountpoint CSI for model weights
10. Lago → Stripe for billing
11. Streaming usage reconciliation (server-side metering as truth)

---

## Security invariants

- **Qdrant tenant RLS** — clients never supply filters; the server builds `group_id == tenant` from the authenticated principal. Tested in CI.
- **Fail-closed auth** — no JWKS / no key match → 401, never a fallback to the body `tenant`.
- **No static AWS keys** — IRSA / EKS Pod Identity + External Secrets; GitHub OIDC for CI→ECR and CI→deploy role.
- **Webhook verification** — Clerk via svix, Stripe via `Stripe-Signature`; both lazy-imported and return 503 until keys/libs are present.
- **Hard budget cap returns 429** (with `Retry-After` + upgrade prompt), never 5xx — over-budget is an expected product state, not an error.

---

## Verification (end-to-end at M7)

Commit a prompt change on a PR → CI → gate → promote → prod serves it → sampled eval catches regression → alert → rollback:

1. **PR** — lint/test/scan/sign + DeepEval faithfulness ≥ 0.80 gate; RAGAS scores as PR comment.
2. **Merge** — digest-pinned tag bumped → Argo sync → rollout status → smoke (answer + citation) → manual approval → promote.
3. **Prod (EKS)** — k6 @ 20 RPS/10 min; Grafana 6-panel green; Langfuse traces with cost + RAGAS + 5% sampled eval; LiteLLM spend → Lago → Stripe line items; Qdrant RLS e2e (tenant A cannot read tenant B → 403/empty).
4. **Regression drill** — worse prompt on branch → nightly faithfulness → 0.78 → DeepEval blocks merge; force-merge to canary → 7-day alert fires ≤ 15 min; Argo rollback → recovers.
5. **Resilience drill** — cordon vLLM node mid-stream → Bifrost fails to Bedrock, no 5xx; kill Langfuse worker → traces buffer in OTel collector; delete a Qdrant replica → Raft re-elects, reads continue.

---

## License

Project code: TBD. Demo dataset `tarekmasryo/rag-qa-logs-corpus-data` is CC BY 4.0. Third-party components retain their upstream licenses (Qdrant Apache 2.0, Qwen 3 Apache 2.0, BGE-M3 MIT, Langfuse MIT, MLflow Apache 2.0, Airflow Apache 2.0, LiteLLM MIT, Lago AGPLv3, Next.js MIT, Clerk proprietary SDK).