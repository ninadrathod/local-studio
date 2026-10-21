#!/usr/bin/env bash
# Full project setup — create backend venv and install Python dependencies.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
VENV_DIR="${BACKEND_DIR}/.venv"

echo "==> Project root: ${ROOT_DIR}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required but was not found." >&2
  exit 1
fi

venv_is_usable() {
  local py="${VENV_DIR}/bin/python"
  local uvicorn_bin="${VENV_DIR}/bin/uvicorn"
  [[ -x "${py}" ]] || return 1
  "${py}" -c "import sys" >/dev/null 2>&1 || return 1
  # Catch relocated projects: console-script shebangs still point at the old path
  if [[ -f "${uvicorn_bin}" ]]; then
    local shebang
    shebang="$(head -1 "${uvicorn_bin}" | sed 's/^#![[:space:]]*//')"
    [[ -n "${shebang}" && -x "${shebang}" ]] || return 1
  fi
  return 0
}

if venv_is_usable; then
  echo "==> Reusing existing virtualenv at backend/.venv"
else
  if [[ -e "${VENV_DIR}" ]]; then
    echo "==> Existing backend/.venv is broken or relocated — recreating"
    rm -rf "${VENV_DIR}"
  else
    echo "==> Creating virtualenv at backend/.venv"
  fi
  python3 -m venv "${VENV_DIR}"
fi

# Prefer the venv interpreter directly (more reliable than relying on activate + PATH)
PYTHON="${VENV_DIR}/bin/python"
PIP=("${PYTHON}" -m pip)

echo "==> Upgrading pip"
"${PIP[@]}" install --upgrade pip

echo "==> Installing backend requirements"
"${PIP[@]}" install -r "${BACKEND_DIR}/requirements.txt"

echo "==> Making scripts executable"
chmod +x "${ROOT_DIR}/scripts/setup.sh" "${ROOT_DIR}/scripts/run.sh" "${ROOT_DIR}/scripts/stop.sh" "${ROOT_DIR}/scripts/update.sh"

HELPERS_DIR="${BACKEND_DIR}/helpers"
if [[ -f "${HELPERS_DIR}/requirements.txt" ]]; then
  echo "==> Installing optional helper deps (subject extraction)"
  "${PIP[@]}" install -r "${HELPERS_DIR}/requirements.txt"

  echo "==> Downloading rembg u2net model (~176MB, cached in ~/.rembg — not in the repo)"
  (
    cd "${HELPERS_DIR}"
    "${PYTHON}" download_model.py
  )

  echo "==> Preparing Real-ESRGAN upscale model (~10MB, cached in ~/.local-studio/models — not in the repo)"
  (
    cd "${HELPERS_DIR}"
    "${PYTHON}" upscale_model.py
  )
fi

echo "==> Initializing preset metadata database"
"${PYTHON}" "${BACKEND_DIR}/database/prepare_db.py"

echo ""
echo "Setup complete."
echo "  Next: ./scripts/run.sh"
echo "  Then open http://localhost:5500"
echo "  Subject helper: python backend/helpers/extract_subject.py photo.jpg -o subject.png"
