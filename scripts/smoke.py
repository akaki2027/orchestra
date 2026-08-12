#!/usr/bin/env python3
"""Hit every route and fail loudly on any 5xx.

This exists because an `isinstance(provider, OllamaProvider)` assert in
routes/catalog.py survived the privacy guard landing — `build()` started
returning a wrapper, the assert began raising, and `/api/local/models` 500'd
for three commits while every other route stayed green. Nothing caught it,
because nothing swept the whole surface.

Usage:  ./run.sh --no-browser &   then   .venv/bin/python scripts/smoke.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8600"

# (method, path, expected statuses). A route that needs a live provider may
# legitimately return 4xx/502; only 5xx from our own code is a failure.
ROUTES: list[tuple[str, str, set[int]]] = [
    ("GET", "/", {200}),
    ("GET", "/static/style.css", {200}),
    ("GET", "/static/app.js", {200}),
    ("GET", "/static/catalog.json", {200}),
    ("GET", "/static/brand/favicon.png", {200}),
    ("GET", "/api/health", {200}),
    ("GET", "/api/config", {200}),
    ("GET", "/api/providers", {200}),
    ("GET", "/api/models", {200}),
    ("GET", "/api/agents", {200}),
    ("GET", "/api/local/models", {200}),
    ("GET", "/api/openrouter/models?q=llama&limit=2", {200, 502}),
    ("GET", "/api/openrouter/models?free=true&limit=2", {200, 502}),
    ("POST", "/api/providers/ollama/test", {200}),
    ("POST", "/api/providers/anthropic/test", {200}),
    ("POST", "/api/providers/openrouter/test", {200}),
    ("POST", "/api/providers/openai_compat/test", {200}),
    # Deliberately malformed: must be a clean 400, never a 500.
    ("POST", "/api/openrouter/starred", {400}, {"id": "no-slash"}),
    ("PUT", "/api/agents/smoke-probe", {400}, {"name": "x", "role": "", "model": {}}),
    ("DELETE", "/api/agents/definitely-not-here", {404}),
]


def call(method: str, path: str, body: dict | None = None) -> int:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except urllib.error.URLError as exc:
        print(f"  cannot reach {BASE} — is it running?  ({exc.reason})")
        raise SystemExit(2)


def main() -> int:
    failures = []
    for route in ROUTES:
        method, path, expected = route[0], route[1], route[2]
        body = route[3] if len(route) > 3 else None
        status = call(method, path, body)
        ok = status in expected
        if not ok:
            failures.append((method, path, status, expected))
        mark = "ok " if ok else "FAIL"
        print(f"  {mark} {status}  {method:6} {path}")

    print()
    if failures:
        print(f"{len(failures)} route(s) wrong:")
        for method, path, status, expected in failures:
            print(f"  {method} {path} returned {status}, expected one of {sorted(expected)}")
        return 1
    print(f"All {len(ROUTES)} routes behaved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
