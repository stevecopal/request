# syntax=docker/dockerfile:1

# ═══════════════════════════════════════════════════════════════════════════
# UnivReq — Dockerfile de PRODUCTION (PostgreSQL + Redis/Channels + PWA)
# Build multi-étage : ① assets Tailwind → ② venv uv → ③ runtime minimale.
# ═══════════════════════════════════════════════════════════════════════════

# ── Stage 1 — Compilation Front-end (Tailwind CSS) ─────────────────────────
FROM node:20-alpine AS assets

WORKDIR /build

COPY package.json package-lock.json tailwind.config.js ./
RUN npm ci --no-audit --no-fund

COPY static ./static
COPY templates ./templates

RUN npm run build \
    && test -s /build/static/css/output.css


# ── Stage 2 — Builder Python (uv, dépendances gelées par uv.lock) ──────────
FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# ①  Verrouillage : pose d'abord le cache des wheels (rebuilds rapides).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ②  Puis le code.
COPY . .
RUN uv sync --frozen --no-dev


# ── Stage 3 — Image runtime finale ─────────────────────────────────────────
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    HOME=/app \
    DJANGO_SETTINGS_MODULE=core.settings

# gosu : permet à l'entrypoint de faire tourner l'app en non-root (appuser).
RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid 1000 \
        --home-dir /app --no-create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

# venv compilé (bytecode) issu du builder — psycopg[binary] embarque libpq.
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser . /app/
# output.css fraîchement compilé par l'étape assets (jamais celui de l'hôte).
COPY --from=assets --chown=appuser:appuser /build/static/css/output.css /app/static/css/output.css
COPY --chown=appuser:appuser entry.sh /app/entry.sh

RUN chmod +x /app/entry.sh \
    && mkdir -p /app/staticfiles /app/media /app/logs \
    && chown -R appuser:appuser /app

EXPOSE 8000

ENTRYPOINT ["/app/entry.sh"]

# ASGI (core.asgi) via le worker uvicorn de gunicorn : HTTP + WebSocket
# (Django Channels) dans un seul processus, scalable par --workers.
CMD ["gunicorn", "core.asgi:application", \
     "--bind=0.0.0.0:8000", \
     "--worker-class=uvicorn.workers.UvicornWorker", \
     "--workers=3", \
     "--timeout=120", \
     "--graceful-timeout=30", \
     "--max-requests=1000", \
     "--max-requests-jitter=100", \
     "--access-logfile=-", \
     "--error-logfile=-", \
     "--log-level=info"]
