#!/usr/bin/env bash
# Refuse to let a credential reach the repo.
#
# "It is gitignored" is a claim, not a check — .env was covered while
# .env.local was not, which is exactly the kind of gap that only shows up after
# a key is public. This tests the tracked tree instead of trusting the list.
set -uo pipefail
cd "$(dirname "$0")/.."

fail=0

# Key shapes, deliberately anchored to the prefix and a plausible length so a
# placeholder like "sk-ant-…" in documentation does not trip it.
PATTERNS='sk-ant-[A-Za-z0-9_-]{24,}|sk-or-v1-[A-Za-z0-9]{24,}|sk-[A-Za-z0-9]{32,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----'

echo "Scanning tracked files for credentials..."
if git grep -nIE "$PATTERNS" -- . ':!scripts/check-secrets.sh'; then
  echo
  echo "FAIL: the matches above are tracked by git."
  fail=1
else
  echo "  clean"
fi

echo "Checking the files that must never be tracked..."
for f in .env .env.local .env.production orchestra.env config.json .orchestra/config.json; do
  if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
    echo "  FAIL: $f is tracked"
    fail=1
  elif ! git check-ignore -q "$f"; then
    echo "  FAIL: $f is not ignored — it would be committed if created"
    fail=1
  else
    echo "  ok  $f ignored"
  fi
done

exit "$fail"
