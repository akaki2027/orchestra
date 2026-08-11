#!/usr/bin/env bash
# Orchestra launcher. Idempotent: safe to run every time.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

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
