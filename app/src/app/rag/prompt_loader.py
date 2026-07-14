"""Prompt + pipeline config loader.

M1: loads from a versioned local file `rag/prompts/rag_system.md` + `pipeline.yaml`.
M3: loads the system prompt by alias `production` from the MLflow Prompt Registry,
falling back to the local file if the registry is unreachable or the prompt is
missing. This is our substitute for Haystack's YAML pipeline serialization (ADR
0003) — the prompt/pipeline config is versioned in MLflow and loaded by alias, so a
prompt change = new version = new `production` alias = re-eval trigger + cache bust.

MLflow API (3.x, `mlflow.genai`):
  load_prompt("prompts:/<name>@<alias>", allow_missing=True) -> Prompt | None
  prompt.template -> the template string (our system prompt has no variables)
Alias-based loads are cached with a 60s TTL (aliases are mutable), so a prompt bump
is picked up within a minute with no restart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings
from app.observability import get_logger

PROMPTS_DIR = Path(__file__).parent / "prompts"
PIPELINE_CONFIG = Path(__file__).parent / "pipeline.yaml"

_SYSTEM_PROMPT_CACHE: str | None = None
_log = get_logger("prompt_loader")


def _load_from_mlflow() -> str | None:
    """Try MLflow Prompt Registry by alias; return template string or None on miss."""
    s = get_settings()
    if not s.mlflow_tracking_uri:
        return None
    try:
        import mlflow  # type: ignore  # optional, heavy dep — guarded
    except Exception as e:  # pragma: no cover - mlflow not installed / import error
        _log.warning("mlflow_unavailable", error=str(e))
        return None
    try:
        mlflow.set_tracking_uri(s.mlflow_tracking_uri)
        uri = f"prompts:/{s.rag_prompt_name}@{s.rag_prompt_alias}"
        prompt = mlflow.genai.load_prompt(uri, allow_missing=True)
        if prompt is None:
            _log.info("prompt_missing_in_registry", uri=uri)
            return None
        template = prompt.template
        # A chat-prompt template is a list of message dicts; our system prompt is text.
        if isinstance(template, list):
            template = "\n".join(m.get("content", "") for m in template if isinstance(m, dict))
        _log.info("prompt_loaded_from_registry", uri=uri, version=getattr(prompt, "version", None))
        return str(template).strip()
    except Exception as e:  # pragma: no cover - registry/network errors
        _log.warning("prompt_registry_load_failed", error=str(e))
        return None


def load_system_prompt(force: bool = False) -> str:
    """Return the RAG system prompt. M3: MLflow Prompt Registry alias `production`,
    falling back to the local file. Cached for the process; pass force=True to re-read."""
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE and not force:
        return _SYSTEM_PROMPT_CACHE
    remote = _load_from_mlflow()
    if remote:
        _SYSTEM_PROMPT_CACHE = remote
        return remote
    path = PROMPTS_DIR / "rag_system.md"
    _SYSTEM_PROMPT_CACHE = path.read_text(encoding="utf-8").strip()
    _log.info("prompt_loaded_from_file", path=str(path))
    return _SYSTEM_PROMPT_CACHE


def load_pipeline_config() -> dict[str, Any]:
    """Retrieval knobs (top_k, rerank_top_k, fusion, etc.). Overridden by Settings at runtime."""
    if PIPELINE_CONFIG.exists():
        return yaml.safe_load(PIPELINE_CONFIG.read_text(encoding="utf-8")) or {}
    return {}


def build_messages(question: str, context_chunks: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Assemble the chat messages: system prompt + a single user turn with context + question."""
    context = "\n\n".join(
        f"[{i + 1}] (source: {c.get('source', '?')}) {c['text']}"
        for i, c in enumerate(context_chunks)
    )
    system = load_system_prompt()
    user = (
        "Answer the question using ONLY the context below. Cite sources as [n]. "
        "If the context does not contain the answer, say you don't know — do not invent.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
