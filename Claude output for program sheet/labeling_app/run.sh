#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -x .venv/bin/python ]; then
  echo "Missing .venv. Run ./setup.sh first." >&2
  exit 1
fi

PORT="${PORT:-8780}"
echo "Starting CAD Feature Recognition at http://127.0.0.1:${PORT}"
exec .venv/bin/python -m uvicorn local_app.main:app --host 127.0.0.1 --port "$PORT"
