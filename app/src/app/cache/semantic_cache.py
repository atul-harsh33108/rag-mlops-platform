"""Semantic cache in front of generation.

M1: exact-match cache (question hash + tenant + corpus_version) — fast, no false hits.
M2: upgrade to Redis LangCache / RedisVL SemanticCache (cosine, distance_threshold=0.90)
keyed by (embedding, tenant_id, corpus_version). The corpus_version in the key is
CRITICAL — when Airflow reindexes (M3), it bumps corpus_version, invalidating all cached
answers so we never serve a stale answer against a changed corpus.
"""

from __future__ import annotations

import hashlib
import json

import redis.asyncio as redis

from app.config import get_settings


class SemanticCache:
    def __init__(self) -> None:
        self._redis = redis.from_url(get_settings().redis_url, decode_responses=True)
        self.enabled = get_settings().cache_enabled
        self.ttl = 60 * 60 * 24  # 24h; short because corpus_version is the real invalidator

    @staticmethod
    def _key(tenant_id: str, corpus_version: int, question: str) -> str:
        h = hashlib.sha256(question.strip().lower().encode()).hexdigest()
        return f"rag:cache:{tenant_id}:v{corpus_version}:{h}"

    async def get(self, tenant_id: str, corpus_version: int, question: str) -> str | None:
        if not self.enabled:
            return None
        raw = await self._redis.get(self._key(tenant_id, corpus_version, question))
        if not raw:
            return None
        try:
            return json.loads(raw)["answer"]
        except Exception:
            return None

    async def set(self, tenant_id: str, corpus_version: int, question: str, answer: str) -> None:
        if not self.enabled:
            return
        await self._redis.set(
            self._key(tenant_id, corpus_version, question),
            json.dumps({"answer": answer, "question": question}),
            ex=self.ttl,
        )

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False
