"""OpenAI-compatible provider.

One adapter covers OpenRouter, LM Studio, vLLM, Groq, together.ai, OpenAI
itself, and Ollama's own /v1 shim — anything speaking /chat/completions.
Coverage per line of code is the highest of any provider here, which matters
for an open-source project whose users all have different setups.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from .base import Caps, Chunk, ModelInfo, Msg, ProviderError, Status


class OpenAICompatProvider:
    id = "openai_compat"
    caps = Caps(json_schema=True, downloadable=False, server_side_research=False)

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        label: str | None = None,
    ) -> None:
        self.base_url = _normalize(base_url)
        self.api_key = api_key or None
        self.label = label or "OpenAI-compatible"

    def configured(self) -> bool:
        # Some local servers (LM Studio, vLLM) need no key, so only the URL is
        # strictly required.
        return bool(self.base_url)

    def is_local(self) -> bool:
        """LM Studio and vLLM on this machine count as local, and should."""
        from urllib.parse import urlparse

        from .. import privacy

        if not self.base_url:
            return False
        return privacy.is_local_host(urlparse(self.base_url).hostname or "")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def status(self) -> Status:
        if not self.configured():
            return Status(state="not_configured", detail="Add a base URL to use this endpoint.")
        try:
            models = await self.list_models()
        except ProviderError as exc:
            return Status(state="unreachable", detail=str(exc))
        return Status(state="ok", detail=f"{len(models)} model(s) available", models=len(models))

    async def list_models(self) -> list[ModelInfo]:
        if not self.configured():
            return []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/models", headers=self._headers())
                if resp.status_code == 401:
                    raise ProviderError("Endpoint rejected the API key.")
                resp.raise_for_status()
                payload = resp.json()
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach {self.base_url}: {exc}") from exc

        entries = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return []
        return [
            ModelInfo(
                id=str(entry.get("id")),
                provider=self.id,
                label=str(entry.get("id")),
                detail=self.label,
            )
            for entry in entries
            if entry.get("id")
        ]

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
        if not self.configured():
            raise ProviderError("This endpoint is not configured.")

        payload: dict[str, Any] = {
            "model": model,
            "messages": ([{"role": "system", "content": system}] if system else [])
            + [m.as_dict() for m in messages],
            "stream": True,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "plan", "schema": json_schema, "strict": True},
            }

        # Structured-output support varies across compatible servers. If the
        # endpoint rejects response_format, retry once without it and let the
        # caller's JSON-repair path take over rather than failing the run.
        try:
            async for chunk in self._stream(payload):
                yield chunk
        except _RetryWithoutSchema:
            payload.pop("response_format", None)
            async for chunk in self._stream(payload):
                yield chunk

    async def _stream(self, payload: dict[str, Any]) -> AsyncIterator[Chunk]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                ) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode(errors="replace")
                        if resp.status_code == 400 and "response_format" in body and "response_format" in payload:
                            raise _RetryWithoutSchema()
                        raise ProviderError(f"Endpoint returned {resp.status_code}: {body[:400]}")

                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        for choice in event.get("choices") or []:
                            piece = (choice.get("delta") or {}).get("content")
                            if piece:
                                yield Chunk(type="text", text=piece)

                        usage = event.get("usage")
                        if usage:
                            yield Chunk(
                                type="usage",
                                data={
                                    "input_tokens": usage.get("prompt_tokens"),
                                    "output_tokens": usage.get("completion_tokens"),
                                },
                            )
        except (ProviderError, _RetryWithoutSchema):
            raise
        except httpx.HTTPError as exc:
            raise ProviderError(f"Request to {self.base_url} failed: {exc}") from exc


class _RetryWithoutSchema(Exception):
    """Internal signal: this endpoint does not accept response_format."""


def _normalize(base_url: str | None) -> str | None:
    """Accept both `https://host` and `https://host/v1`, plus /v1beta variants."""
    if not base_url:
        return None
    url = base_url.strip().rstrip("/")
    if not url:
        return None
    if "/v1" not in url:
        url = f"{url}/v1"
    return url
