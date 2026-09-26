#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11 or newer is required"'
"$PYTHON_BIN" -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python check_install.py

printf '\nSetup complete. Start the app with: ./run.sh\n'
