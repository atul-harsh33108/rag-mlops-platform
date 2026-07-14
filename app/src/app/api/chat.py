"""POST /chat — streaming RAG answer with citations.

Flow: resolve tenant (M6: from JWT/API-key; M1: from body) → get corpus_version → semantic
cache lookup → hybrid retrieve (tenant-scoped) → build messages → stream LLM tokens as SSE
→ cache the full answer → record cost (M2: into Langfuse trace; M7: metered to LiteLLM).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import Principal, get_principal
from app.cache.semantic_cache import SemanticCache
from app.clients.llm import LLMClient
from app.db import ensure_tenant, get_corpus_version, session_context, tenant_exists
from app.observability import Tracer, get_logger
from app.rag.prompt_loader import build_messages
from app.rag.retriever import HybridRetriever
from app.rate_limit import limiter, set_tenant_on_state, tenant_key_func

router = APIRouter(tags=["chat"])
log = get_logger("chat")
tracer = Tracer()


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    # M6: ignored when an Authorization header resolves a Principal (tenant comes from JWT/
    # API key). Required only in the no-auth local/eval path (M1 mode).
    tenant: str = Field(..., min_length=1, max_length=64, description="tenant_id (group_id)")
    stream: bool = True
    # Eval-only: include retrieved context texts in the non-stream response so RAGAS
    # (context precision/recall) can run. Default off — never expose contexts to clients in prod.
    include_contexts: bool = False


class ChatResponse(BaseModel):
    answer: str
    citations: list[dict]
    cached: bool
    contexts: list[str] = Field(
        default_factory=list, description="retrieved chunk texts (eval-only)"
    )


@router.post("/chat")
@limiter.limit("60/minute", key_func=tenant_key_func)
async def chat(
    req: ChatRequest,
    request: Request,
    principal: Principal | None = Depends(get_principal),
    _: None = Depends(set_tenant_on_state),
):
    # --- resolve tenant (M6: JWT/API-key; M1: body) ---
    if principal is not None:
        tenant = principal.tenant_id
        # Auto-provision the Clerk org as a tenant row (M7 replaces this with a webhook).
        async with session_context() as session:
            await ensure_tenant(session, tenant, name=tenant)
            corpus_version = await get_corpus_version(session)
    else:
        tenant = req.tenant
        async with session_context() as session:
            if not await tenant_exists(session, tenant):
                raise HTTPException(status_code=404, detail=f"unknown tenant: {tenant}")
            corpus_version = await get_corpus_version(session)

    cache = SemanticCache()
    citations: list[dict] = []
    trace = tracer.start_trace(name="chat", tenant_id=tenant, question=req.question)

    # --- cache lookup (exact-match in M1; cosine semantic in M2) ---
    cached = await cache.get(tenant, corpus_version, req.question)
    if cached is not None:
        return ChatResponse(answer=cached, citations=[], cached=True)

    # --- retrieve (tenant RLS enforced inside HybridRetriever via filter_builder) ---
    async with tracer.span("retrieve", tenant=tenant, question=req.question) as span:
        retriever = HybridRetriever(tenant)
        chunks = await retriever.retrieve(req.question)
        citations = [
            {
                "source": c["source"],
                "doc_id": c["doc_id"],
                "chunk_idx": c["chunk_idx"],
                "score": c["score"],
            }
            for c in chunks
        ]
        span["num_chunks"] = len(chunks)

    if not chunks:
        # No context found — abstain rather than hallucinate (system prompt also enforces this).
        no_info = "I don't have enough information to answer that."
        await cache.set(tenant, corpus_version, req.question, no_info)
        return ChatResponse(answer=no_info, citations=[], cached=False)

    messages = build_messages(req.question, chunks)
    llm = LLMClient()

    if not req.stream:
        async with tracer.span("generate") as span:
            answer = await llm.chat(messages, temperature=0.1)
            span["tokens_out"] = len(answer) // 4  # rough until LiteLLM meters (M3)
        await cache.set(tenant, corpus_version, req.question, answer)
        tracer.record_generation(
            trace,
            name="generate",
            model=llm._model,
            input=messages,
            output=answer,
            tokens_out=len(answer) // 4,
            metadata={"corpus_version": corpus_version, "num_chunks": len(chunks)},
        )
        return ChatResponse(
            answer=answer,
            citations=citations,
            cached=False,
            contexts=[c["text"] for c in chunks] if req.include_contexts else [],
        )

    # --- SSE streaming ---
    async def event_stream() -> AsyncIterator[bytes]:
        full = []
        # first event: citations so the UI can render sources before tokens arrive
        yield _sse("citations", citations)
        async with tracer.span("generate_stream", tenant=tenant) as span:
            async for tok in llm.stream_chat(messages, temperature=0.1):
                full.append(tok)
                yield _sse("token", tok)
            answer = "".join(full)
            span["tokens_out"] = len(answer) // 4
        await cache.set(tenant, corpus_version, req.question, answer)
        tracer.record_generation(
            trace,
            name="generate_stream",
            model=llm._model,
            input=messages,
            output=answer,
            tokens_out=len(answer) // 4,
            metadata={"corpus_version": corpus_version, "num_chunks": len(chunks)},
        )
        yield _sse("done", {"cached": False, "corpus_version": corpus_version})

    from fastapi.responses import StreamingResponse

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse(event: str, data: object) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()
