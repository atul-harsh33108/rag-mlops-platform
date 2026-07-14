"""API routers."""

from app.api import chat, health, ingest, keys

routers = [health.router, chat.router, ingest.router, keys.router]

__all__ = ["routers", "chat", "health", "ingest", "keys"]
