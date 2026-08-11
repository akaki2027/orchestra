"""FastAPI application: JSON API under /api, static UI at /."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .routes import agents as agents_routes
from .routes import catalog as catalog_routes
from .routes import chat as chat_routes
from .routes import providers as provider_routes
from .routes import runs as runs_routes

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app() -> FastAPI:
    app = FastAPI(title="Orchestra", version="0.1.0")

    app.include_router(provider_routes.router, prefix="/api")
    app.include_router(catalog_routes.router, prefix="/api")
    app.include_router(agents_routes.router, prefix="/api")
    app.include_router(chat_routes.router, prefix="/api")
    app.include_router(runs_routes.router, prefix="/api")

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
        async def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app()
