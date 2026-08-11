"""Entry point: `python -m orchestra` or the `orchestra` console script."""

from __future__ import annotations

import argparse
import sys
import webbrowser

DEFAULT_PORT = 8600


def main() -> int:
    parser = argparse.ArgumentParser(prog="orchestra", description="Orchestra — local AI orchestration portal")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address. Defaults to localhost; Orchestra has no auth, so only "
        "expose it beyond your machine on a network you trust.",
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser window")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes (development)")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("Dependencies are missing. Run ./run.sh (or pip install -r requirements.txt).", file=sys.stderr)
        return 1

    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"\n  WARNING: binding to {args.host}. Orchestra has no authentication,\n"
            "  so anyone who can reach this port can use your API keys and models.\n",
            file=sys.stderr,
        )

    print(f"\n  Orchestra → {url}\n")
    if not args.no_browser:
        webbrowser.open(url)

    uvicorn.run(
        "orchestra.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
