# Architecture Decision Records

| # | Decision | Status |
|---|---|---|
| 0001 | LiteLLM proxy as unified LLM gateway (not MLflow AI Gateway) | Accepted |
| 0002 | Airflow 3.x for orchestration (Dataset triggers for re-indexing) | Accepted |
| 0003 | LangChain/LangGraph for retrieval (avoid deprecated `langchain-community`) | Accepted |
| 0004 | Feast deferred — not needed for pure RAG | Accepted |
| 0005 | Qdrant over Milvus (corpus < 100M vectors) | Accepted |
| 0006 | Clerk for demo auth; Keycloak documented for self-hosted | Accepted |