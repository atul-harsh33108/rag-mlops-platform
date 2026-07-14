"""API routers."""

from app.api import admin, chat, health, ingest, keys, webhooks

routers = [health.router, chat.router, ingest.router, keys.router, admin.router, webhooks.router]

__all__ = ["routers", "admin", "chat", "health", "ingest", "keys", "webhooks"]
