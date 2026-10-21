#!/usr/bin/env bash
# Pull the latest code, stop the running app, and start it again.
# Always runs all three steps, even when there is nothing new to pull.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

git pull
./scripts/stop.sh
exec ./scripts/run.sh
