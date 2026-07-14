"""Typed configuration loaded from environment (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_prefix="")

    env: str = "dev"
    log_level: str = "INFO"
    tz: str = "UTC"

    # Qdrant
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "docs"
    qdrant_api_key: str | None = None

    # TEI embeddings (BGE-M3)
    tei_host: str = "tei"
    tei_port: int = 80
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024

    # LLM serving. M1: Ollama directly. M3: set litellm_proxy_url and route through it.
    ollama_host: str = "http://ollama:11434"
    ollama_model: str = "qwen3:14b"
    ollama_num_ctx: int = 8192
    litellm_proxy_url: str | None = None  # when set, used instead of Ollama directly
    litellm_api_key: str | None = None  # LiteLLM master/key — sent as Authorization

    # MLflow Prompt Registry (M3). System prompt is loaded by alias `production`,
    # falling back to the local file if MLflow is unreachable.
    mlflow_tracking_uri: str | None = None
    rag_prompt_name: str = "rag-system"
    rag_prompt_alias: str = "production"

    # Redis semantic cache
    redis_url: str = "redis://redis:6379/0"
    langcache_distance_threshold: float = 0.90
    cache_enabled: bool = True

    # Postgres metadata
    database_url: str = "postgresql+psycopg://mlops:CHANGE_ME@postgres:5432/mlops"

    # Retrieval knobs
    retrieve_top_k: int = 50  # candidates before rerank
    rerank_top_k: int = 8  # final context size
    corpus_version: int = 1  # overridden from DB at runtime; env is the fallback

    # Auth (M6) — Clerk (demo) / Keycloak (self-host). When CLERK_JWKS_URL is unset, auth
    # is disabled and /chat falls back to the body `tenant` (M1 mode, used by evals/seed).
    jwt_issuer: str | None = None
    jwt_audience: str = "rag-platform"
    clerk_jwks_url: str | None = None
    clerk_authorized_parties: str = ""  # comma-separated allowed `azp` origins
    auth_enabled: bool = False  # True in prod (M6+) to enforce JWT/API-key
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60  # per tenant; per-plan override at M7

    # --- Billing + metering + sampled evals (M7) ---
    # Lago (open-source billing) — LiteLLM's `lago` success_callback reports spend as a
    # billable metric; we also create customers/subscriptions here. All optional/guarded.
    lago_api_base: str | None = None  # e.g. https://api.lago.dev/api/v1
    lago_api_key: str | None = None
    lago_webhook_host: str | None = None  # LiteLLM needs this to receive Lago webhooks
    lago_billable_metric_code: str = "llm-spend"  # the billable metric units = spend_usd
    # Stripe — webhook updates tenant plan + budget on subscription events.
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    # Clerk — webhook syncs Clerk org -> tenant row (group_id = org id).
    clerk_webhook_secret: str | None = None
    # Production-sampled eval: fraction of /chat traffic judged for regression alerting.
    eval_sample_rate: float = 0.05
    # Judge model name (routed via LiteLLM `judge`). Falls back to the chat model.
    judge_model: str | None = None

    # Observability (M1 minimal stubs; full at M2)
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "rag-app"


@lru_cache
def get_settings() -> Settings:
    return Settings()
