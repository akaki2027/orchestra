"""Ollama provider — local models, and the only backend that can *download*.

Plain httpx rather than a client library: Ollama's HTTP surface is small and
stable, and one less dependency keeps `pip install` fast for people cloning the
repo.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from .base import Caps, Chunk, ModelInfo, Msg, ProviderError, Status


class OllamaProvider:
    id = "ollama"
    label = "Ollama (local)"
    caps = Caps(json_schema=True, downloadable=True, server_side_research=False)

    def __init__(self, host: str | None = None) -> None:
        self.host = (host or "http://127.0.0.1:11434").rstrip("/")

    def configured(self) -> bool:
        # Ollama needs no credentials; a host is always present.
        return True

    def is_local(self) -> bool:
        """Usually true — but not if the user pointed Ollama at another box."""
        from urllib.parse import urlparse

        from .. import privacy

        return privacy.is_local_host(urlparse(self.host).hostname or "")

    def _client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.host, timeout=timeout)

    async def status(self) -> Status:
        try:
            async with self._client(timeout=3.0) as client:
                resp = await client.get("/api/tags")
                resp.raise_for_status()
                installed = resp.json().get("models") or []
        except httpx.ConnectError:
            return Status(
                state="unreachable",
                detail=f"No Ollama server at {self.host}. Start it with `ollama serve`.",
            )
        except httpx.HTTPError as exc:
            return Status(state="error", detail=str(exc))

        if not installed:
            return Status(
                state="ok",
                detail="Connected, but no models are installed yet. Pull one from the Models tab.",
                models=0,
            )
        return Status(state="ok", detail=f"{len(installed)} model(s) installed", models=len(installed))

    async def list_models(self) -> list[ModelInfo]:
        try:
            async with self._client(timeout=5.0) as client:
                resp = await client.get("/api/tags")
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError:
            # An unreachable local server is a normal state, not an error worth
            # blowing up a combined model list over.
            return []

        models: list[ModelInfo] = []
        for entry in payload.get("models") or []:
            details = entry.get("details") or {}
            quant = details.get("quantization_level")
            params = details.get("parameter_size")
            detail = " · ".join(x for x in (params, quant) if x) or None
            models.append(
                ModelInfo(
                    id=entry["name"],
                    provider=self.id,
                    label=entry["name"],
                    local=True,
                    size_bytes=entry.get("size"),
                    detail=detail,
                )
            )
        return sorted(models, key=lambda m: m.id)

    async def loaded_models(self) -> set[str]:
        """Names currently resident in memory — drives the 'loaded' badge."""
        try:
            async with self._client(timeout=3.0) as client:
                resp = await client.get("/api/ps")
                resp.raise_for_status()
                return {m["name"] for m in resp.json().get("models") or []}
        except (httpx.HTTPError, KeyError):
            return set()

    async def chat(
        self,
        model: str,
        messages: list[Msg],
        *,
        system: str | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int = 8192,
        tools: list[str] | None = None,
    ) -> AsyncIterator[Chunk]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": ([{"role": "system", "content": system}] if system else [])
            + [m.as_dict() for m in messages],
            "stream": True,
            "options": {"num_predict": max_tokens},
        }
        if temperature is not None:
            payload["options"]["temperature"] = temperature
        if json_schema is not None:
            # Ollama constrains decoding to a JSON schema via `format`.
            payload["format"] = json_schema

        try:
            # Generous timeout: a cold local model can take a while to load into
            # memory before the first token appears.
            async with self._client(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
                async with client.stream("POST", "/api/chat", json=payload) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode(errors="replace")
                        raise ProviderError(f"Ollama returned {resp.status_code}: {body[:400]}")
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if event.get("error"):
                            raise ProviderError(f"Ollama: {event['error']}")
                        piece = (event.get("message") or {}).get("content") or ""
                        if piece:
                            yield Chunk(type="text", text=piece)
                        if event.get("done"):
                            yield Chunk(
                                type="usage",
                                data={
                                    "input_tokens": event.get("prompt_eval_count"),
                                    "output_tokens": event.get("eval_count"),
                                },
                            )
        except httpx.ConnectError as exc:
            raise ProviderError(
                f"Could not reach Ollama at {self.host}. Start it with `ollama serve`."
            ) from exc

    # -- model management (the download portal) ---------------------------

    async def pull(self, name: str) -> AsyncIterator[dict[str, Any]]:
        """Stream pull progress. Accepts library names and `hf.co/user/repo:quant`."""
        async with self._client(timeout=httpx.Timeout(None, connect=10.0)) as client:
            async with client.stream("POST", "/api/pull", json={"model": name, "stream": True}) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode(errors="replace")
                    raise ProviderError(f"Pull failed ({resp.status_code}): {body[:400]}")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    async def delete(self, name: str) -> None:
        async with self._client(timeout=30.0) as client:
            resp = await client.request("DELETE", "/api/delete", json={"model": name})
            if resp.status_code >= 400:
                raise ProviderError(f"Delete failed ({resp.status_code}): {resp.text[:400]}")
