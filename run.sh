#!/usr/bin/env bash
# Orchestra launcher. Idempotent: safe to run every time.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

# Load .env if it is there. Keys supplied this way are never written to
# ~/.orchestra/config.json — the app reads the environment on every load and
# leaves the file alone — which makes .env the right place for a key you do not
# want persisted. Names are printed, values never are.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
  LOADED=$(sed -n 's/^[[:space:]]*\([A-Z_][A-Z0-9_]*\)=.*/\1/p' .env | tr '\n' ' ')
  echo "Loaded from .env: ${LOADED:-nothing}"
fi

if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3.10+ is required but '$PY' was not found." >&2
  echo "Install it from https://python.org, then run this script again." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo "First run: creating virtual environment..."
  "$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# Only reinstall when requirements change.
STAMP=.venv/.requirements-stamp
if [ ! -f "$STAMP" ] || ! cmp -s requirements.txt "$STAMP"; then
  echo "Installing dependencies..."
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -r requirements.txt
  cp requirements.txt "$STAMP"
fi

exec python -m orchestra "$@"
