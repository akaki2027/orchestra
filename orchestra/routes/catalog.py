"""The model download portal: installed / browse / pull / delete."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import StreamingResponse

from ..providers import build
from ..providers.base import ProviderError
from ..providers.ollama import OllamaProvider

router = APIRouter(tags=["catalog"])


def _ollama() -> OllamaProvider:
    provider = build("ollama")
    assert isinstance(provider, OllamaProvider)
    return provider


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


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"
