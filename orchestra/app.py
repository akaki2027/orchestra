"""FastAPI application: JSON API under /api, static UI at /."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .routes import agents as agents_routes
from .routes import catalog as catalog_routes
from .routes import chat as chat_routes
from .routes import hardware as hardware_routes
from .routes import providers as provider_routes
from .routes import runs as runs_routes
from .routes import tools as tools_routes

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app() -> FastAPI:
    app = FastAPI(title="Orchestra", version="0.1.0")

    app.include_router(provider_routes.router, prefix="/api")
    app.include_router(catalog_routes.router, prefix="/api")
    app.include_router(agents_routes.router, prefix="/api")
    app.include_router(chat_routes.router, prefix="/api")
    app.include_router(hardware_routes.router, prefix="/api")
    app.include_router(runs_routes.router, prefix="/api")
    app.include_router(tools_routes.router, prefix="/api")

    @app.get("/api/health")
    async def health() -> dict:
        cfg = config.load()
        return {
            "ok": True,
            "version": app.version,
            "home": str(config.HOME),
            "configured": bool(cfg["orchestrator"]["provider"]),
        }

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/")
        async def index() -> HTMLResponse:
            """Serve index.html with cache-busted asset URLs.

            Without this, editing style.css or app.js changes nothing until the
            user knows to hard-refresh — which they shouldn't have to, and which
            made a rebuilt UI look like it had not shipped at all. The stamp is
            derived from file mtimes, so the browser refetches exactly when an
            asset actually changed and caches it otherwise.
            """
            html = (WEB_DIR / "index.html").read_text()
            for asset in ("style.css", "app.js"):
                try:
                    stamp = int((WEB_DIR / asset).stat().st_mtime)
                except OSError:
                    continue
                html = html.replace(f"/static/{asset}", f"/static/{asset}?v={stamp}")
            # The document itself must never be cached, or it would keep
            # handing out yesterday's stamps.
            return HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})

    return app


app = create_app()
