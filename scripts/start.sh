#!/bin/sh
set -eu
cd /app

echo "[start] Alembic upgrade head..."
alembic upgrade head

echo "[start] Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
