"""API routers."""

from app.api import chat, health, ingest

routers = [health.router, chat.router, ingest.router]

__all__ = ["routers", "chat", "health", "ingest"]
