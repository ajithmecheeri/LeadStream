#!/bin/sh
# Apply migrations (as the service's schema owner), then start the API.
set -e
python -m alembic upgrade head
if [ "${JOBSEARCH_ENV:-local}" = "local" ]; then
  exec uvicorn jobsearch.main:app --host 0.0.0.0 --port 8100 --reload
fi
exec uvicorn jobsearch.main:app --host 0.0.0.0 --port 8100 --workers "${WEB_CONCURRENCY:-1}"
