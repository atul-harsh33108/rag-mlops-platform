"""LLM client: Ollama (M1, local) or LiteLLM gateway (M3+, prod). Same interface.

M1 talks to Ollama directly via its OpenAI-compatible `/v1/chat/completions`
endpoint so the swap to LiteLLM (also OpenAI-compatible) at M3 is a base_url change.
Both support SSE streaming.

M3: when routing through LiteLLM we DROP the Ollama-only `options.num_ctx` payload —
LiteLLM's `drop_params` would discard it for non-Ollama fallbacks (Bedrock/vLLM at M5),
but we also avoid sending it so the request is provider-agnostic. `num_ctx` is only
meaningful for the direct-Ollama path. We also pass the LiteLLM api key as a Bearer
token (LiteLLM rejects calls without a key once master_key is set).

M7: we send `stream_options.include_usage=true` so the provider emits a final chunk
carrying real token counts (OpenAI/LiteLLM/vLLM support this; Ollama ignores it). The
client stashes that usage on `last_usage` for the meter to record — the server-side
truth that fixes LiteLLM's streaming under-counting. When no usage arrives (Ollama),
`last_usage` stays None and the caller falls back to an estimate (flagged `estimated`).

M7 billing attribution: `with_tenant(tenant_id, key_id)` sets the LiteLLM `metadata`
(`tenant_id`, `key_id`) + `user` on every call, so LiteLLM_SpendLogs rows carry the
tenant and the tenant_spend_monthly view groups correctly.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import get_settings


class LLMClient:
    def __init__(self, model: str | None = None) -> None:
        s = get_settings()
        self._via_gateway = bool(s.litellm_proxy_url)
        if self._via_gateway:
            self._base = s.litellm_proxy_url.rstrip("/")
            self._model = model or s.ollama_model  # LiteLLM routes by model name
            self._headers = (
                {"Authorization": f"Bearer {s.litellm_api_key}"} if s.litellm_api_key else {}
            )
        else:
            self._base = s.ollama_host.rstrip("/")
            self._model = model or s.ollama_model
            self._headers = {}
        # M7 billing attribution — set via with_tenant(); included in every payload.
        self._tenant_id: str | None = None
        self._key_id: int | None = None
        # M7 usage capture — populated from the provider's final streamed chunk.
        self.last_usage: dict[str, int] | None = None

    def with_tenant(self, tenant_id: str, key_id: int | None = None) -> LLMClient:
        """Set billing attribution (LiteLLM metadata.user + metadata.tenant_id/key_id)."""
        self._tenant_id = tenant_id
        self._key_id = key_id
        return self

    def _payload(
        self, messages: list[dict], *, temperature: float, stream: bool
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        # `options.num_ctx` is Ollama-specific — only send it on the direct-Ollama path.
        if not self._via_gateway:
            payload["options"] = {"num_ctx": get_settings().ollama_num_ctx}
        # M7: request usage in the final stream chunk (OpenAI/LiteLLM/vLLM). Ollama ignores
        # the field, so this is safe to always send.
        if stream:
            payload["stream_options"] = {"include_usage": True}
        # M7 billing attribution — LiteLLM logs metadata + user into LiteLLM_SpendLogs.
        if self._tenant_id:
            payload["user"] = self._tenant_id
            payload["metadata"] = {"tenant_id": self._tenant_id, "key_id": self._key_id}
        return payload

    @staticmethod
    def _usage_from(chunk: dict[str, Any]) -> dict[str, int] | None:
        u = chunk.get("usage")
        if not u or not isinstance(u, dict):
            return None
        return {
            "prompt_tokens": int(u.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(u.get("completion_tokens", 0) or 0),
            "total_tokens": int(u.get("total_tokens", 0) or 0),
        }

    async def stream_chat(
        self, messages: list[dict], *, temperature: float = 0.2
    ) -> AsyncIterator[str]:
        """Yield token deltas (OpenAI-style `delta.content`). Works for Ollama and LiteLLM.

        On completion, `self.last_usage` holds the provider-reported usage (or None if the
        provider didn't emit a final usage chunk — caller should then estimate).
        """
        self.last_usage = None
        payload = self._payload(messages, temperature=temperature, stream=True)
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as c,
            c.stream(
                "POST", f"{self._base}/v1/chat/completions", json=payload, headers=self._headers
            ) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                # The final usage chunk has an empty choices list + a usage object.
                usage = self._usage_from(chunk)
                if usage:
                    self.last_usage = usage
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                tok = delta.get("content")
                if tok:
                    yield tok

    async def chat(self, messages: list[dict], *, temperature: float = 0.0) -> str:
        """Non-streaming completion (used by evals/seed/judge, not the /chat hot path)."""
        self.last_usage = None
        payload = self._payload(messages, temperature=temperature, stream=False)
        async with httpx.AsyncClient(timeout=120.0) as c:
            resp = await c.post(
                f"{self._base}/v1/chat/completions", json=payload, headers=self._headers
            )
            resp.raise_for_status()
            body = resp.json()
            self.last_usage = self._usage_from(body)
            return body["choices"][0]["message"]["content"]
