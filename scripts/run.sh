#!/usr/bin/env bash
# Run the project — start the API and a static frontend server in the background.
# Returns once both are up; they keep running (even after the terminal closes)
# until ./scripts/stop.sh. Output goes to logs/api.log and logs/frontend.log.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
VENV_DIR="${BACKEND_DIR}/.venv"
PYTHON="${VENV_DIR}/bin/python"
LOG_DIR="${ROOT_DIR}/logs"

API_HOST="${API_HOST:-0.0.0.0}"
# Fixed: the frontend always calls the API on port 8000 (script.js apiBaseUrl).
API_PORT=8000
FRONTEND_PORT="${FRONTEND_PORT:-5500}"

# Only used when startup fails: stop whatever this run started, so nothing half-up is left behind.
cleanup() {
  if [[ -n "${API_PID:-}" ]] && kill -0 "${API_PID}" 2>/dev/null; then
    kill "${API_PID}" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    kill "${FRONTEND_PID}" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
  else
    return 1
  fi
}

if [[ ! -x "${PYTHON}" ]]; then
  echo "Error: backend/.venv not found or incomplete. Run ./scripts/setup.sh first." >&2
  exit 1
fi

# Fail fast when the venv was moved (broken console-script shebangs) or deps are missing
if ! "${PYTHON}" -c "import uvicorn, multipart, fastapi, PIL" >/dev/null 2>&1; then
  echo "Error: backend virtualenv is broken or missing dependencies." >&2
  echo "  Fix: ./scripts/setup.sh" >&2
  exit 1
fi

if port_in_use "${API_PORT}"; then
  echo "Error: port ${API_PORT} is already in use (API)." >&2
  echo "  Stop it with ./scripts/stop.sh (the API must use 8000: the frontend calls that port)." >&2
  exit 1
fi

if port_in_use "${FRONTEND_PORT}"; then
  echo "Error: port ${FRONTEND_PORT} is already in use (frontend)." >&2
  echo "  Stop the other process, or run: FRONTEND_PORT=5501 ./scripts/run.sh" >&2
  exit 1
fi

# presets.db is local (gitignored): create/migrate it and add any presets that
# arrived with a git pull. Existing rows and popular counts are kept.
echo "==> Preparing preset database"
"${PYTHON}" "${BACKEND_DIR}/database/prepare_db.py"

mkdir -p "${LOG_DIR}"

# nohup + exec: the PIDs are the servers themselves, and they ignore the
# terminal hang-up, so they survive this script exiting or the SSH session closing.
echo "==> Starting API on http://localhost:${API_PORT}"
(
  cd "${BACKEND_DIR}"
  exec nohup "${PYTHON}" -m uvicorn app.main:app --reload --host "${API_HOST}" --port "${API_PORT}"
) >"${LOG_DIR}/api.log" 2>&1 </dev/null &
API_PID=$!

echo "==> Starting frontend on http://localhost:${FRONTEND_PORT}"
(
  cd "${ROOT_DIR}"
  exec nohup "${PYTHON}" -m http.server "${FRONTEND_PORT}"
) >"${LOG_DIR}/frontend.log" 2>&1 </dev/null &
FRONTEND_PID=$!

# Wait for both listeners (up to ~30 s, for slower machines like a Raspberry Pi);
# fail if either died or health never comes up.
ready=0
for _ in $(seq 1 60); do
  if ! kill -0 "${API_PID}" 2>/dev/null; then
    echo "Error: API process exited early. See logs/api.log:" >&2
    tail -n 20 "${LOG_DIR}/api.log" >&2 || true
    exit 1
  fi
  if ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    echo "Error: frontend process exited early. See logs/frontend.log:" >&2
    tail -n 20 "${LOG_DIR}/frontend.log" >&2 || true
    exit 1
  fi
  if curl -sf "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.5
done

if [[ "${ready}" -eq 1 ]]; then
  echo "==> API health: ok"
else
  echo "Error: API did not become healthy on port ${API_PORT}." >&2
  echo "  Tip: stop other listeners, or run ./scripts/setup.sh then try again." >&2
  exit 1
fi

# Started fine: leave the servers running when this script exits.
trap - EXIT INT TERM

echo ""
echo "Open http://localhost:${FRONTEND_PORT} in your browser."
echo "Running in the background — logs: logs/api.log, logs/frontend.log"
echo "Stop with: ./scripts/stop.sh"
