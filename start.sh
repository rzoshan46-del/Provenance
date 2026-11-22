#!/usr/bin/env bash
# start.sh — production startup script
# Initializes database and runs migrations safely without deleting existing data.
set -e

echo "[start] Initializing database schema if needed…"
python -c "from app.db import init_db; from app.seed import seed_users, seed_projects; init_db(); seed_users(); seed_projects()"

echo "[start] Starting Provenance server…"
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}"
