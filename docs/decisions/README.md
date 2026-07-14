# Architecture Decision Records

| # | Decision | Status |
|---|---|---|
| 0001 | LiteLLM proxy as unified LLM gateway (not MLflow AI Gateway) | Accepted |
| 0002 | Airflow 3.x for orchestration (Dataset triggers for re-indexing) | Accepted |
| 0003 | LangChain/LangGraph for retrieval (avoid deprecated `langchain-community`) | Accepted |
| 0004 | Feast deferred — not needed for pure RAG | Accepted |
| 0005 | Qdrant over Milvus (corpus < 100M vectors) | Accepted |
| 0006 | Clerk for demo auth; Keycloak documented for self-hosted | Accepted |
| 0007 | Airflow 3.x orchestration (Dataset triggers for re-indexing) | Accepted |
| 0008 | Bifrost cascade — vLLM primary, Bedrock fallback (M5 EKS) | Accepted |
| 0009 | S3 + Mountpoint CSI for model weights (not EBS) (M5 EKS) | Accepted |
| 0010 | Billing: LiteLLM → Lago → Stripe (M7) | Accepted |
| 0011 | Server-side usage metering + reconciliation (streaming under-count fix) (M7) | Accepted |