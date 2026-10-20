#!/bin/sh
# ═══════════════════════════════════════════════════════════════════════════
# UnivReq — entrypoint de production
# ① permissions des volumes  ② attente PostgreSQL  ③ collectstatic + migrate
# ④ démarrage de la commande passée (gunicorn par défaut) en non-root.
# ═══════════════════════════════════════════════════════════════════════════
set -e

APP_USER="appuser"
VENV_PYTHON="/app/.venv/bin/python"

export PATH="/app/.venv/bin:$PATH"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-core.settings}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1

RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"
RUN_COLLECTSTATIC="${RUN_COLLECTSTATIC:-1}"

# ── 1/4 — Permissions des volumes ──────────────────────────────────────────
echo "=== [1/4] Permissions des volumes (media, staticfiles, logs) ==="
mkdir -p /app/media /app/staticfiles /app/logs
chown -R "$APP_USER:$APP_USER" /app/media /app/staticfiles /app/logs

# ── 2/4 — Attente de la disponibilité de PostgreSQL ───────────────────────
if [ -n "$DB_HOST" ]; then
    echo "=== [2/4] Attente de PostgreSQL ($DB_HOST:${DB_PORT:-5432})... ==="
    until "$VENV_PYTHON" -c "import socket; s = socket.socket(); s.settimeout(2); s.connect(('${DB_HOST}', ${DB_PORT:-5432}))" 2>/dev/null; do
        echo "PostgreSQL n'est pas encore prêt, nouvelle tentative dans 2 secondes..."
        sleep 2
    done
    echo "PostgreSQL est en ligne et accessible."
fi

# ── 3/4 — Statiques (WhiteNoise) puis migrations ───────────────────────────
if [ "$RUN_COLLECTSTATIC" = "1" ]; then
    echo "=== [3/4] collectstatic → /app/staticfiles (WhiteNoise) ==="
    gosu "$APP_USER" "$VENV_PYTHON" manage.py collectstatic --noinput
fi

if [ "$RUN_MIGRATIONS" = "1" ]; then
    echo "=== [3/4] migrate ==="
    gosu "$APP_USER" "$VENV_PYTHON" manage.py migrate --noinput
fi

# ── 4/4 — Démarrage en non-root ────────────────────────────────────────────
echo "=== [4/4] Démarrage de la commande : $* ==="
exec gosu "$APP_USER" env \
    PATH="$PATH" \
    HOME=/app \
    DJANGO_SETTINGS_MODULE="$DJANGO_SETTINGS_MODULE" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    "$@"
