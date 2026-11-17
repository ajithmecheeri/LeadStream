#!/usr/bin/env bash
# Run the API, the background worker, and the web app together in one
# terminal. Ctrl+C stops them all.
set -euo pipefail
cd "$(dirname "$0")/.."

# On Ctrl+C or exit, stop every process this script started (uvicorn, its reloader, worker, next dev).
trap 'trap - INT TERM EXIT; echo; echo "Stopping API, worker and web..."; kill 0 2>/dev/null; wait 2>/dev/null' INT TERM EXIT

make --no-print-directory dev-api 2>&1 | sed -u 's/^/[api] /' &
# Give the API a head start so migrations finish before the worker starts and the first page loads.
for _ in $(seq 1 30); do curl -sf http://localhost:8000/healthz >/dev/null 2>&1 && break; sleep 1; done
make --no-print-directory dev-worker 2>&1 | sed -u 's/^/[worker] /' &
make --no-print-directory dev-web 2>&1 | sed -u 's/^/[web] /' &

echo "LeadStream: http://localhost:3000   API docs: http://localhost:8000/api/docs   (Ctrl+C to stop)"
echo "The worker doesn't reload on code changes: Ctrl+C and 'make dev' again after editing a task."
wait
