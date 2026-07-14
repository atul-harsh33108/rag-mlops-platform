"""Server-side usage metering (M7). Records a `usage_events` row after every /chat — the
app's own source of truth for what the model actually emitted.

This is the fix for LiteLLM's streaming under-counting (8-15% on client disconnect): LiteLLM
counts what it proxied, not what the model produced. We capture the real `usage` from the
provider's final streamed chunk (OpenAI `stream_options.include_usage`), and when the provider
doesn't return usage (e.g. Ollama), we estimate from the assembled answer and flag
`estimated=TRUE` so the reconciliation DAG knows which rows are exact vs approximate.

Cost is computed from a per-model price table (USD per 1K tokens). In prod LiteLLM already
computes spend into LiteLLM_SpendLogs; this table keeps the app-side metering independent so
the two can be reconciled.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# USD per 1K tokens. Default used for unknown models. Keep conservative (over-estimate) so the
# budget cap errs toward protecting the tenant.
PRICE_PER_1K: dict[str, tuple[float, float]] = {
    # model: (input_per_1k, output_per_1k)
    "qwen3:14b": (0.0007, 0.0014),  # self-hosted vLLM: amortized GPU cost, rough
    "judge": (0.003, 0.015),  # Bedrock Claude Sonnet (Bifrost fallback / judge)
}

DEFAULT_PRICE = (0.001, 0.002)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) — only used when the provider gave no usage."""
    return max(1, len(text) // 4)


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pin, pout = PRICE_PER_1K.get(model, DEFAULT_PRICE)
    return round((prompt_tokens / 1000.0) * pin + (completion_tokens / 1000.0) * pout, 6)


async def record_usage(
    session: AsyncSession,
    *,
    tenant_id: str,
    key_id: int | None,
    request_id: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_usd: float | None = None,
    estimated: bool = False,
    cached: bool = False,
) -> int:
    """Insert a usage_events row. Returns the row id. Commits."""
    total = prompt_tokens + completion_tokens
    if cost_usd is None:
        cost_usd = compute_cost(model, prompt_tokens, completion_tokens)
    res = await session.execute(
        text(
            "INSERT INTO usage_events "
            "(tenant_id, key_id, request_id, model, prompt_tokens, completion_tokens, "
            " total_tokens, cost_usd, estimated, cached) "
            "VALUES (:t, :k, :r, :m, :pi, :co, :tt, :c, :e, :ca) RETURNING id"
        ),
        {
            "t": tenant_id,
            "k": key_id,
            "r": request_id,
            "m": model,
            "pi": prompt_tokens,
            "co": completion_tokens,
            "tt": total,
            "c": cost_usd,
            "e": estimated,
            "ca": cached,
        },
    )
    usage_id = int(res.scalar_one())
    await session.commit()
    return usage_id
