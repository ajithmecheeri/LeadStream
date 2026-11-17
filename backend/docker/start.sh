#!/bin/sh
# Apply migrations (as the schema owner), then start the API.
set -e
python -m alembic upgrade head
if [ "${SEED_DEMO:-false}" = "true" ]; then python -m app.seed; fi
if [ "${ENV:-local}" = "local" ]; then
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --proxy-headers
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-2}" --proxy-headers --forwarded-allow-ips='*'
