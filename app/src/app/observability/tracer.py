"""Tracer — M1 structlog spans + M2 Langfuse v3 trace/generation export (optional).

When LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST are set, each /chat request creates a Langfuse
trace with a generation carrying the prompt, completion, model, token usage and cost, and
accepts RAGAS scores (record_score) so quality trends alongside cost in the Grafana
dashboard. OTel export (OpenLLMetry) is wired separately in otel.py — pushed to the
collector → Langfuse /api/public/otel.

The interface (span, record_cost, record_score) is stable so /chat doesn't change when
tracing is off (local dev with no Langfuse): spans are still logged as structured JSON.
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.observability.logging import get_logger

try:  # optional dependency — only used when configured
    from langfuse import Langfuse  # type: ignore

    _LANGFUSE_AVAILABLE = True
except Exception:  # pragma: no cover - import guard
    _LANGFUSE_AVAILABLE = False


def _langfuse_enabled() -> bool:
    return bool(
        _LANGFUSE_AVAILABLE
        and os.environ.get("LANGFUSE_PUBLIC_KEY")
        and os.environ.get("LANGFUSE_SECRET_KEY")
        and os.environ.get("LANGFUSE_HOST")
    )


def get_langfuse() -> Langfuse | None:
    if not _langfuse_enabled():
        return None
    return Langfuse()  # reads LANGFUSE_* env vars


class Tracer:
    """M1: logs spans as structured JSON. M2: also exports a Langfuse trace + generation."""

    def __init__(self) -> None:
        self._log = get_logger("tracer")
        self._lf = get_langfuse()

    @asynccontextmanager
    async def span(self, name: str, **fields: Any) -> AsyncIterator[dict[str, Any]]:
        ctx: dict[str, Any] = {"name": name, **fields}
        t0 = time.perf_counter()
        try:
            yield ctx
        finally:
            ctx["duration_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            self._log.info("span", **ctx)

    # ---- Langfuse-backed reporting (used by /chat when tracing is on) ----

    def start_trace(
        self, *, name: str, tenant_id: str, question: str, metadata: dict | None = None
    ):
        if not self._lf:
            return None
        return self._lf.trace(
            name=name,
            metadata={"tenant_id": tenant_id, "question": question, **(metadata or {})},
        )

    def record_generation(
        self,
        trace,
        *,
        name: str,
        model: str,
        input: dict | list,
        output: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        metadata: dict | None = None,
    ):
        if not self._lf or not trace:
            return
        self._lf.generation(
            trace_id=trace.id,
            name=name,
            model=model,
            input=input,
            output=output,
            usage_details={
                "input": tokens_in,
                "output": tokens_out,
                "total": tokens_in + tokens_out,
                "cost": cost_usd,
            },
            metadata=metadata or {},
        )

    def record_score(self, trace, *, name: str, value: float, comment: str = ""):
        """Push a RAGAS/eval score onto a trace so it trends in Langfuse + Grafana."""
        if not self._lf or not trace:
            return
        self._lf.score(trace_id=trace.id, name=name, value=value, comment=comment)
