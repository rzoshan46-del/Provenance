#!/usr/bin/env bash
# start.sh — production startup script
# Seeds the demo database if empty, then launches uvicorn.
set -e

echo "[start] Seeding demo database…"
python demo_reset.py

echo "[start] Starting Provenance server…"
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers 1
