#!/usr/bin/env bash
# Stop processes listening on the API and frontend ports (defaults: 8000, 5500).
# Waits until both ports are free, so ./scripts/run.sh can start right after.
set -euo pipefail

API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5500}"

listeners() {
  lsof -tiTCP:"${API_PORT}" -sTCP:LISTEN 2>/dev/null || true
  lsof -tiTCP:"${FRONTEND_PORT}" -sTCP:LISTEN 2>/dev/null || true
}

kill $(listeners) 2>/dev/null || true

# Give the servers up to ~10 s to shut down cleanly, then force-kill stragglers.
for _ in $(seq 1 20); do
  [[ -z "$(listeners)" ]] && exit 0
  sleep 0.5
done
kill -9 $(listeners) 2>/dev/null || true
sleep 0.5
