"""LLM client: Ollama (M1, local) or LiteLLM gateway (M3+, prod). Same interface.

M1 talks to Ollama directly via its OpenAI-compatible `/v1/chat/completions`
endpoint so the swap to LiteLLM (also OpenAI-compatible) at M3 is a base_url change.
Both support SSE streaming.

M3: when routing through LiteLLM we DROP the Ollama-only `options.num_ctx` payload —
LiteLLM's `drop_params` would discard it for non-Ollama fallbacks (Bedrock/vLLM at M5),
but we also avoid sending it so the request is provider-agnostic. `num_ctx` is only
meaningful for the direct-Ollama path. We also pass the LiteLLM api key as a Bearer
token (LiteLLM rejects calls without a key once master_key is set).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.config import get_settings


class LLMClient:
    def __init__(self) -> None:
        s = get_settings()
        self._via_gateway = bool(s.litellm_proxy_url)
        if self._via_gateway:
            self._base = s.litellm_proxy_url.rstrip("/")
            self._model = s.ollama_model  # LiteLLM routes by model name
            self._headers = (
                {"Authorization": f"Bearer {s.litellm_api_key}"} if s.litellm_api_key else {}
            )
        else:
            self._base = s.ollama_host.rstrip("/")
            self._model = s.ollama_model
            self._headers = {}

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
        return payload

    async def stream_chat(
        self, messages: list[dict], *, temperature: float = 0.2
    ) -> AsyncIterator[str]:
        """Yield token deltas (OpenAI-style `delta.content`). Works for Ollama and LiteLLM."""
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
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                tok = delta.get("content")
                if tok:
                    yield tok

    async def chat(self, messages: list[dict], *, temperature: float = 0.0) -> str:
        """Non-streaming completion (used by evals/seed, not the /chat hot path)."""
        payload = self._payload(messages, temperature=temperature, stream=False)
        async with httpx.AsyncClient(timeout=120.0) as c:
            resp = await c.post(
                f"{self._base}/v1/chat/completions", json=payload, headers=self._headers
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
