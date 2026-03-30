#!/bin/bash
set -euo pipefail
cd /app

echo "[start] Alembic upgrade head..."
alembic upgrade head

echo "[start] Seed / réparation des embeddings (idempotent)..."
python -m scripts.seed_db

echo "[start] Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
