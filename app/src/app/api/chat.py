"""POST /chat — streaming RAG answer with citations.

Flow: resolve tenant (M6: from JWT/API-key; M1: from body) -> get corpus_version -> semantic
cache lookup -> M7 budget check (429 + upgrade prompt if over cap) -> hybrid retrieve
(tenant-scoped) -> build messages -> stream LLM tokens as SSE -> cache the full answer ->
M7 meter the real token usage to usage_events -> M7 maybe sample for prod eval.

M7 billing attribution: the LLM call carries LiteLLM `metadata.tenant_id` + `user` so
LiteLLM_SpendLogs groups by tenant (the tenant_spend_monthly view + Lago billable metric).
Metering uses the provider's real `usage` from the final streamed chunk (stream_options
include_usage); when the provider gives none (Ollama), we estimate and flag `estimated`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.auth import Principal, get_principal
from app.billing.meter import estimate_tokens, record_usage
from app.billing.spend import BudgetExceeded, assert_under_budget, load_tenant_billing
from app.cache.semantic_cache import SemanticCache
from app.clients.llm import LLMClient
from app.db import ensure_tenant, get_corpus_version, session_context, tenant_exists
from app.evals import maybe_sample_and_eval
from app.observability import Tracer, get_logger
from app.rag.prompt_loader import build_messages
from app.rag.retriever import HybridRetriever
from app.rate_limit import limiter, plan_rate_limit, set_tenant_on_state, tenant_key_func

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


def _budget_exceeded_response(exc: BudgetExceeded) -> JSONResponse:
    """429 with an upgrade prompt (NOT a 5xx). The client may retry after upgrading."""
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": "3600"},
        content={
            "detail": "monthly budget exceeded",
            "plan": exc.plan,
            "spent_usd": round(exc.spent, 2),
            "cap_usd": round(exc.cap, 2),
            "upgrade": "Upgrade your plan to continue this month.",
        },
    )


@router.post("/chat")
@limiter.limit(plan_rate_limit, key_func=tenant_key_func)
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

    request_id = uuid.uuid4().hex
    cache = SemanticCache()
    citations: list[dict] = []
    trace = tracer.start_trace(name="chat", tenant_id=tenant, question=req.question)

    # --- cache lookup (exact-match in M1; cosine semantic in M2) ---
    cached = await cache.get(tenant, corpus_version, req.question)
    if cached is not None:
        # Cache hits are free (no LLM call) but still a "turn" — meter a cached row so the
        # admin usage view reflects real traffic. 0 tokens, 0 cost.
        async with session_context() as session:
            await record_usage(
                session,
                tenant_id=tenant,
                key_id=principal.key_id if principal else None,
                request_id=request_id,
                model=LLMClient()._model,
                cached=True,
            )
        return ChatResponse(answer=cached, citations=[], cached=True)

    # --- M7 budget enforcement: over-cap -> 429 upgrade (before the expensive generate) ---
    async with session_context() as session:
        billing = await load_tenant_billing(session, tenant)
        if billing is not None:
            try:
                await assert_under_budget(session, billing, principal.key_id if principal else None)
            except BudgetExceeded as exc:
                log.warning("budget_exceeded", tenant=tenant, plan=exc.plan)
                return _budget_exceeded_response(exc)

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
        async with session_context() as session:
            await record_usage(
                session,
                tenant_id=tenant,
                key_id=principal.key_id if principal else None,
                request_id=request_id,
                model=LLMClient()._model,
                completion_tokens=estimate_tokens(no_info),
                estimated=True,
            )
        return ChatResponse(answer=no_info, citations=[], cached=False)

    messages = build_messages(req.question, chunks)
    llm = LLMClient().with_tenant(tenant, principal.key_id if principal else None)
    model_name = llm._model  # noqa: SLF001 — read for metering attribution

    if not req.stream:
        async with tracer.span("generate") as span:
            answer = await llm.chat(messages, temperature=0.1)
            usage = llm.last_usage or {
                "prompt_tokens": estimate_tokens(req.question),
                "completion_tokens": estimate_tokens(answer),
                "total_tokens": 0,
            }
            estimated = llm.last_usage is None
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
            span["tokens_out"] = usage["completion_tokens"]
        await cache.set(tenant, corpus_version, req.question, answer)
        async with session_context() as session:
            await record_usage(
                session,
                tenant_id=tenant,
                key_id=principal.key_id if principal else None,
                request_id=request_id,
                model=model_name,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                estimated=estimated,
            )
        tracer.record_generation(
            trace,
            name="generate",
            model=model_name,
            input=messages,
            output=answer,
            tokens_in=usage["prompt_tokens"],
            tokens_out=usage["completion_tokens"],
            metadata={"corpus_version": corpus_version, "num_chunks": len(chunks)},
        )
        maybe_sample_and_eval(
            tenant_id=tenant,
            trace=trace,
            question=req.question,
            answer=answer,
            contexts=[c["text"] for c in chunks],
        )
        return ChatResponse(
            answer=answer,
            citations=citations,
            cached=False,
            contexts=[c["text"] for c in chunks] if req.include_contexts else [],
        )

    # --- SSE streaming ---
    async def event_stream() -> AsyncIterator[bytes]:
        full: list[str] = []
        # first event: citations so the UI can render sources before tokens arrive
        yield _sse("citations", citations)
        async with tracer.span("generate_stream", tenant=tenant) as span:
            async for tok in llm.stream_chat(messages, temperature=0.1):
                full.append(tok)
                yield _sse("token", tok)
            answer = "".join(full)
            usage = llm.last_usage or {
                "prompt_tokens": estimate_tokens(req.question),
                "completion_tokens": estimate_tokens(answer),
                "total_tokens": 0,
            }
            estimated = llm.last_usage is None
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
            span["tokens_out"] = usage["completion_tokens"]
        await cache.set(tenant, corpus_version, req.question, answer)
        # M7 meter the real streamed usage (the under-count fix). Done after the stream
        # completes so the row reflects what the model actually emitted.
        async with session_context() as session:
            await record_usage(
                session,
                tenant_id=tenant,
                key_id=principal.key_id if principal else None,
                request_id=request_id,
                model=model_name,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                estimated=estimated,
            )
        tracer.record_generation(
            trace,
            name="generate_stream",
            model=model_name,
            input=messages,
            output=answer,
            tokens_in=usage["prompt_tokens"],
            tokens_out=usage["completion_tokens"],
            metadata={"corpus_version": corpus_version, "num_chunks": len(chunks)},
        )
        maybe_sample_and_eval(
            tenant_id=tenant,
            trace=trace,
            question=req.question,
            answer=answer,
            contexts=[c["text"] for c in chunks],
        )
        yield _sse("done", {"cached": False, "corpus_version": corpus_version})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse(event: str, data: object) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()
