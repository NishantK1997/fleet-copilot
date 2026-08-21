#!/usr/bin/env sh
set -eu

mkdir -p /app/data
alembic upgrade head

if [ -f scripts/seed_telemetry.py ]; then
  python scripts/seed_telemetry.py
fi

if [ -f scripts/seed_users.py ]; then
  python scripts/seed_users.py
fi

exec uvicorn app.main:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}"
