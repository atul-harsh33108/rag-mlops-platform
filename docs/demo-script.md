# Demo script — "minimum impressive" (end of M1 + Langfuse from M2)

The smallest slice that already looks production-grade — for portfolio/interview use. Achievable in ~1 focused day from Milestones 1–2.

## Setup (~2 min)
```bash
cp .env.example .env && task dev:up core,ai,mlops && task seed
```
- Qdrant + TEI/BGE-M3 + Ollama/Qwen3:14b + FastAPI + Langfuse + Redis cache + Open WebUI all up.
- 500 `support_faq` + `product_docs` docs loaded into Qdrant.

## The demo (narrate as you go)

1. **Open WebUI** → `http://127.0.0.1:3000`
   Ask: *"How do I reset my password?"*
   → grounded answer + citation chips pointing to the source docs. **(streaming, cited, sub-second TTFB)**

2. **FastAPI OpenAPI** → `http://127.0.0.1:8000/docs`
   → clean auto-generated docs; `/chat` SSE endpoint visible; `/health` liveness.

3. **Langfuse** → `http://127.0.0.1:3001`
   → the single-turn trace shows: retrieval (which chunks, scores), generation (tokens, model, TTFT), **cost in $**, latency, and a **RAGAS faithfulness score** attached.
   → "this is eval-driven, not vibe-driven — every answer is scored."

4. **Resilience micro-demo**
   `docker stop mlops-ollama-1` mid-stream → app returns a clean degraded message (no 5xx). Restart → answers resume. **(graceful degradation, observable)**

## Talking points
- "Retrieval is hybrid — dense BGE-M3 + BM25 + BGE-reranker cross-encoder rerank."
- "Tenant isolation is server-enforced — Qdrant filters are built from the JWT, clients can't supply them."
- "Every call is traced and costed; a golden Q&A set gates regressions in CI."
- "Same code deploys to local K8s, AWS EKS, and any cloud via one Helm chart (later milestones)."

## Teardown
```bash
task dev:down
```