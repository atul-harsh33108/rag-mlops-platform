# FastAPI RAG service. Built from the app/ context (compose.core.yml sets context: ../app).
# Multi-stage: uv installs into a venv, copied into a slim runtime image.
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
WORKDIR /app
# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
# deps first for cache
COPY pyproject.toml ./
RUN uv sync --no-install-project --no-dev
COPY src ./src
# --extra billing installs svix + stripe for Clerk/Stripe webhook signature
# verification (M7). Imported lazily so the app boots without them; webhooks
# return 503 until installed.
RUN uv sync --no-dev --extra billing

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    PATH="/app/.venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates tzdata \
    && ln -snf /usr/share/zoneinfo/UTC /etc/localtime && echo UTC > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app /app
EXPOSE 8000
# Run under uvicorn directly from the venv (PATH set above).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]