"""Direct chat: one model, no orchestration."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse

from ..providers import build
from ..providers.base import Msg, ProviderError

router = APIRouter(tags=["chat"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/chat")
async def chat(payload: dict[str, Any] = Body(...)) -> StreamingResponse:
    provider_id = (payload.get("provider") or "").strip()
    model = (payload.get("model") or "").strip()
    raw_messages = payload.get("messages") or []
    system = payload.get("system")

    async def events():
        if not provider_id or not model:
            yield sse({"type": "error", "message": "Pick a provider and model first."})
            return
        try:
            provider = build(provider_id)
        except KeyError:
            yield sse({"type": "error", "message": f"Unknown provider: {provider_id}"})
            return

        messages = [
            Msg(role="assistant" if m.get("role") == "assistant" else "user", content=m.get("content") or "")
            for m in raw_messages
            if (m.get("content") or "").strip()
        ]
        if not messages:
            yield sse({"type": "error", "message": "Nothing to send."})
            return

        try:
            async for chunk in provider.chat(model, messages, system=system):
                if chunk.type == "text":
                    yield sse({"type": "token", "text": chunk.text})
                elif chunk.type == "usage":
                    yield sse({"type": "usage", **chunk.data})
                elif chunk.type == "tool":
                    yield sse({"type": "tool", **chunk.data})
            yield sse({"type": "done"})
        except ProviderError as exc:
            yield sse({"type": "error", "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            yield sse({"type": "error", "message": f"Unexpected failure: {exc}"})

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)
