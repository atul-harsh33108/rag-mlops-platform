# Architecture

## Data flow

```
User ──/chat (SSE)──▶ FastAPI app ──(JWT tenant_id)──▶ filter_builder.build(group_id)
                         │                                  │
                         │                                  ▼
                         │      Qdrant search (Filter MUST group_id) ◀── RLS enforced here
                         │                                  │
                         │      Redis LangCache (key: embed+tenant+corpus_version)
                         │            │
                         │      BGE-reranker-v2-m3 (top-50 → top-8)
                         │            │
                         ▼            ▼
                    LangChain prompt ──▶ LiteLLM proxy ──▶ Ollama (local) / vLLM (prod) / Bedrock (fallback)
                         │                                       │
                         │              OpenLLMetry/OTel ──────────┤
                         ▼                                       ▼
                    Langfuse trace (cost + RAGAS scores)   LiteLLM_SpendLogs (per-tenant)
                                                              │
                                                              ▼
                                          Airflow reindex_on_change bumps corpus_version
                                          (invalidates cache; re-embeds; re-evals)
```

## Repo layout

```
mlops/
├── .github/workflows/{ci,deploy,eval-pr,eval-nightly}.yml
├── app/                # FastAPI RAG service (uv, pydantic v2, LangChain)
│   └── src/app/{main,api,rag,gateway,qdrant,cache,auth,billing,observability,scripts}/
├── pipelines/dags/     # Airflow 3.x DAGs (ingest/chunk/embed/index/eval/reindex)
├── evals/               # golden_dataset.jsonl + DeepEval gate + RAGAS runner
├── ui/                  # Next.js 16 + Vercel AI SDK + React 19 (M6)
├── helm/mlops-platform/ # umbrella chart + values-{kind,eks,generic}.yaml
├── infra/terraform/    # EKS v21.x, vpc/ecr/rds/s3/irsa, S3+DynamoDB state
├── docker/             # compose.{core,ai,mlops,observability}.yml + Dockerfiles
├── data/{corpus,seed}/
└── docs/               # this file + ADRs + runbooks + demo-script
```

## Environments

| Env | Runtime | Vector DB | LLM | Metadata | Deploy |
|---|---|---|---|---|---|
| dev (local) | Docker Compose | Qdrant single-node | Ollama Qwen3:14b | Postgres (compose) | `task dev:up` |
| dev (k8s) | k3d/kind + Helm umbrella | Qdrant (chart) | Ollama | Postgres (chart) | Argo CD |
| prod | EKS + Karpenter | Qdrant 3-node Raft | vLLM on g6e + Bedrock fallback | RDS Postgres | Argo CD + Terraform |
| generic | any K8s | Qdrant | any via LiteLLM | Postgres | `helm install -f values-generic.yaml` |

## Security boundary

The **single point of tenant isolation** is `app/src/app/qdrant/filter_builder.py`: it builds the Qdrant `Filter` from the JWT `tenant_id` claim, and every retriever path MUST go through it. Clients never supply filters. CI asserts every `search` payload contains a `group_id` filter; a missing filter is treated as a security bug.