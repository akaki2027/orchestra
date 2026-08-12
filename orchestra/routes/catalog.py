"""The model download portal: installed / browse / pull / delete."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import StreamingResponse

from .. import config
from ..providers import build
from ..providers.base import ProviderError

router = APIRouter(tags=["catalog"])


def _ollama():
    """The Ollama provider, as the registry hands it out.

    Deliberately untyped, with no isinstance check: `build()` returns a
    GuardedProvider wrapper, so narrowing to OllamaProvider raises at runtime.
    That assert shipped and 500'd this whole route for three commits. The
    wrapper forwards `pull`, `delete`, and `loaded_models` via __getattr__,
    which is everything this module calls.
    """
    return build("ollama")


@router.get("/local/models")
async def installed_models() -> dict[str, Any]:
    """Installed local models, annotated with which are resident in memory."""
    provider = _ollama()
    status = await provider.status()
    if status.state != "ok":
        return {"available": False, "status": status.as_dict(), "models": []}

    models = await provider.list_models()
    loaded = await provider.loaded_models()
    return {
        "available": True,
        "status": status.as_dict(),
        "models": [{**m.as_dict(), "loaded": m.id in loaded} for m in models],
    }


@router.post("/local/pull")
async def pull_model(payload: dict[str, Any] = Body(...)) -> StreamingResponse:
    """Stream download progress as SSE.

    Accepts an Ollama library name (`qwen2.5:7b`) or a Hugging Face GGUF
    reference (`hf.co/user/repo:Q4_K_M`) — Ollama resolves both.
    """
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Which model should be pulled?")

    provider = _ollama()

    async def events():
        try:
            async for update in provider.pull(name):
                # Ollama reports per-layer byte counts; forward them verbatim so
                # the client can render a real progress bar.
                yield _sse(
                    {
                        "type": "progress",
                        "status": update.get("status"),
                        "digest": update.get("digest"),
                        "completed": update.get("completed"),
                        "total": update.get("total"),
                    }
                )
            yield _sse({"type": "done", "name": name})
        except ProviderError as exc:
            yield _sse({"type": "error", "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            yield _sse({"type": "error", "message": f"Pull failed: {exc}"})

    return StreamingResponse(events(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.delete("/local/models/{name:path}")
async def delete_model(name: str) -> dict[str, Any]:
    try:
        await _ollama().delete(name)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": name}


# -- OpenRouter: browse 400+ hosted models, star the ones you'll actually use --


def _openrouter():
    """Same wrapper caveat as _ollama: no isinstance narrowing."""
    return build("openrouter")


@router.get("/openrouter/models")
async def openrouter_models(
    q: str = "",
    free: bool = False,
    vision: bool = False,
    limit: int = 60,
) -> dict[str, Any]:
    provider = _openrouter()
    try:
        result = await provider.search(
            query=q, free_only=free, vision_only=vision, limit=max(1, min(limit, 200))
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {**result, "configured": provider.configured()}


@router.post("/openrouter/starred")
async def star_model(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Star or unstar a model id.

    Accepts ids the catalog has never heard of on purpose — a model released
    this morning should not be gated on this app's cache.
    """
    model_id = (payload.get("id") or "").strip()
    if not model_id or "/" not in model_id:
        raise HTTPException(
            status_code=400,
            detail="Give a full OpenRouter model id, like anthropic/claude-opus-5.",
        )

    cfg = config.load()
    starred = list((cfg["providers"].get("openrouter") or {}).get("starred") or [])
    if payload.get("starred") is False or (payload.get("starred") is None and model_id in starred):
        starred = [m for m in starred if m != model_id]
    elif model_id not in starred:
        starred.append(model_id)

    config.update({"providers": {"openrouter": {"starred": starred}}})
    return {"starred": starred}


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"
