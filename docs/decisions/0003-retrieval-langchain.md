# ADR 0003 — LangChain/LangGraph for retrieval

**Status:** Accepted

## Context

2026 research recommends Haystack 2.30.x for production RAG (YAML-serialized pipelines, built-in hybrid + rerank, strong type safety). User selected LangChain/LangGraph.

## Decision

Use **LangChain/LangGraph** — `langchain-core` + `langchain-qdrant` only. Hand-roll the BGE-reranker-v2-m3 cross-encoder step. Use **LangGraph** for any multi-step/agentic flows. **Do NOT** start new code on `langchain-community` (being deprecated).

## Rationale

- User's pick; LangChain remains the broadest integration ecosystem and LangGraph gives agentic capability.

## Consequences

- We lose Haystack's built-in hybrid + rerank + YAML pipeline serialization. Mitigations:
  - Hybrid retrieval: use Qdrant's native sparse vectors (BM25) + dense, fused via reciprocal rank fusion in `app/src/app/rag/retriever.py`.
  - Rerank: hand-roll a LangChain retriever wrapping BGE-reranker-v2-m3 (TEI `/rerank` endpoint).
  - Pipeline versioning (the thing Haystack YAML gave us for free): store the pipeline config + system prompt as versions in **MLflow Prompt Registry** and load by tag `prod`. `app/src/app/rag/prompt_loader.py` handles this.
- Avoid `langchain-community` — use standalone `langchain-qdrant`, `langchain-text-splitters`, etc.