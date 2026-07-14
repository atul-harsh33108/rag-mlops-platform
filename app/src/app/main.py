"""FastAPI app entrypoint. Assembles routers + configures logging on startup.

Run: `uvicorn app.main:app` (the Dockerfile does this)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routers
from app.config import get_settings
from app.observability import configure_logging, get_logger, setup_otel


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    setup_otel()  # no-op if OTEL_EXPORTER_OTLP_ENDPOINT unset
    log = get_logger("startup")
    s = get_settings()
    log.info("starting", env=s.env, model=s.ollama_model, collection=s.qdrant_collection)
    yield
    log.info("shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="RAG Knowledge-Base / Support-Assistant",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for r in routers:
        app.include_router(r)
    return app


app = create_app()
