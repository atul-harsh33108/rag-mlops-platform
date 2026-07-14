"""Production-sampled eval (M7). On each /chat we Bernoulli-sample at EVAL_SAMPLE_RATE
(default 5%) and, for sampled turns, ask a judge LLM for a lightweight faithfulness +
answer-relevancy score. Scores are:

  1. posted onto the Langfuse trace (Tracer.record_score) so they trend in Grafana, and
  2. written to the sampled_evals table, which the prod_eval_alerts DAG rolls up into a
     7-day regression alert (Alertmanager webhook).

This is deliberately lightweight (one judge call, JSON output) so 5% of traffic is cheap
enough to run always-on. The judge gets its own LiteLLM key + budget at M7 (config.eks.yaml
routes `judge` -> Bedrock Claude; locally -> Ollama). Full reference-based RAGAS
(context precision/recall, answer correctness) stays in the nightly GitHub Actions suite.

The eval runs in a fire-and-forget asyncio task created by /chat; this module must NEVER
raise into the request path — every failure is caught and logged.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text

from app.clients.llm import LLMClient
from app.config import get_settings
from app.db import session_context
from app.observability import Tracer, get_logger

_log = get_logger("evals.sampled")


def _should_sample(rate: float) -> bool:
    """Bernoulli sample. `rate` is the configured EVAL_SAMPLE_RATE (0..1)."""
    import random

    return random.random() < rate


_JUDGE_SYSTEM = (
    "You are a strict RAG quality judge. Score the answer against the retrieved context and "
    "the question. Respond with ONLY a JSON object, no prose:\n"
    '{"faithfulness": <0..1>, "answer_relevancy": <0..1>}\n'
    "- faithfulness: fraction of claims in the answer that are directly supported by the "
    "context (1.0 = fully grounded, 0.0 = hallucinated). If the answer says it lacks info, "
    "score faithfulness 1.0 (abstention is honest).\n"
    "- answer_relevancy: how well the answer addresses the question (1.0 = directly, 0.0 = off)."
)


def _judge_messages(question: str, answer: str, contexts: list[str]) -> list[dict]:
    ctx = "\n\n---\n\n".join(contexts) if contexts else "(no context retrieved)"
    user = f"QUESTION:\n{question}\n\nCONTEXT:\n{ctx}\n\nANSWER:\n{answer}"
    return [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {"role": "user", "content": user},
    ]


def _parse_scores(raw: str) -> tuple[float | None, float | None]:
    """Extract the two scores from the judge's JSON (tolerant of surrounding prose)."""
    m = re.search(r"\{[^{}]*\}", raw, re.S)
    if not m:
        return None, None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, None
    f = obj.get("faithfulness")
    r = obj.get("answer_relevancy")
    return (
        float(f) if isinstance(f, (int, float)) else None,
        float(r) if isinstance(r, (int, float)) else None,
    )


async def _judge(
    question: str, answer: str, contexts: list[str]
) -> tuple[float | None, float | None]:
    s = get_settings()
    judge = LLMClient(model=s.judge_model or s.ollama_model)
    try:
        raw = await judge.chat(_judge_messages(question, answer, contexts), temperature=0.0)
    except Exception as e:  # judge unavailable (no LLM endpoint) — drop, don't fail /chat
        _log.warning("judge call failed", error=str(e))
        return None, None
    return _parse_scores(raw)


async def _persist(
    tenant_id: str,
    trace_id: str | None,
    question: str,
    answer: str,
    contexts: list[str],
    faithfulness: float | None,
    relevancy: float | None,
) -> None:
    async with session_context() as session:
        await session.execute(
            text(
                "INSERT INTO sampled_evals "
                "(tenant_id, trace_id, question, answer, contexts, faithfulness, "
                " answer_relevancy, sampled_at, evaluated_at) "
                "VALUES (:t, :tr, :q, :a, :c, :f, :r, now(), now())"
            ),
            {
                "t": tenant_id,
                "tr": trace_id,
                "q": question,
                "a": answer,
                "c": json.dumps(contexts),
                "f": faithfulness,
                "r": relevancy,
            },
        )
        await session.commit()


async def _run_sampled_eval(
    *,
    tenant_id: str,
    trace: Any,
    question: str,
    answer: str,
    contexts: list[str],
) -> None:
    """Do the actual judge + persist + score. Isolated so all errors are swallowed."""
    faith, rel = await _judge(question, answer, contexts)
    trace_id = getattr(trace, "id", None) if trace else None
    try:
        await _persist(tenant_id, trace_id, question, answer, contexts, faith, rel)
    except Exception as e:
        _log.warning("sampled_evals persist failed", error=str(e))
    if trace is not None and (faith is not None or rel is not None):
        tr = Tracer()
        if faith is not None:
            tr.record_score(trace, name="faithfulness", value=faith)
        if rel is not None:
            tr.record_score(trace, name="answer_relevancy", value=rel)
    _log.info("sampled_eval", tenant=tenant_id, faithfulness=faith, relevancy=rel)


def maybe_sample_and_eval(
    *,
    tenant_id: str,
    trace: Any,
    question: str,
    answer: str,
    contexts: list[str],
) -> None:
    """If sampled this turn, schedule the eval as a background task. Never raises.

    Called from /chat after generation. `contexts` are the retrieved chunk texts (the same
    ones passed to include_contexts in the eval path). Synchronous sampling decision +
    fire-and-forget scheduling — returns immediately.
    """
    rate = get_settings().eval_sample_rate
    if rate <= 0 or not _should_sample(rate):
        return
    import asyncio

    try:
        asyncio.create_task(
            _run_sampled_eval(
                tenant_id=tenant_id,
                trace=trace,
                question=question,
                answer=answer,
                contexts=contexts,
            )
        )
    except RuntimeError:
        # No running loop (e.g. called from a sync context in tests) — skip silently.
        _log.debug("sampled_eval skipped: no running loop")


__all__ = ["maybe_sample_and_eval"]
