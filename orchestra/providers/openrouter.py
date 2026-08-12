"""OpenRouter — one key, several hundred models from every major lab.

This is a dedicated provider rather than a base_url pointed at the generic
OpenAI-compatible adapter, because OpenRouter's catalog is the feature. It
returns pricing, context length, modality, and moderation status per model, and
throwing that away would make the picker a wall of 400 opaque slugs.

The catalog is browsed and starred separately from the model pickers. A native
select with 400 options is technically usable and practically hostile, so the
Models tab is where you search the full list and the pickers show what you
starred — plus any id you type by hand, so a model released this morning is
never blocked on this app knowing about it.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

import httpx

from .base import Caps, Chunk, ModelInfo, Msg, ProviderError, Status

BASE_URL = "https://openrouter.ai/api/v1"

# OpenRouter uses these for its public leaderboards. Sending them is how an
# open-source app shows up as itself rather than as anonymous traffic.
ATTRIBUTION = {
    "HTTP-Referer": "https://github.com/orchestra-agents/orchestra",
    "X-Title": "Orchestra",
}

CATALOG_TTL = 900  # seconds; the catalog moves, but not every keystroke.


class OpenRouterProvider:
    id = "openrouter"
    label = "OpenRouter"
    caps = Caps(json_schema=True, downloadable=False, server_side_research=False)

    _catalog: list[dict[str, Any]] = []
    _fetched_at: float = 0.0

    def __init__(self, api_key: str | None = None, starred: list[str] | None = None) -> None:
        self.api_key = api_key or None
        self.starred = list(starred or [])

    def configured(self) -> bool:
        return bool(self.api_key)

    def is_local(self) -> bool:
        return False

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **ATTRIBUTION,
        }

    # -- catalog ----------------------------------------------------------

    async def catalog(self, force: bool = False) -> list[dict[str, Any]]:
        """Every model OpenRouter serves, normalized and cached.

        The models endpoint needs no key, so the catalog is browsable before
        you have signed up — useful for deciding whether to.
        """
        cls = type(self)
        if cls._catalog and not force and (time.time() - cls._fetched_at) < CATALOG_TTL:
            return cls._catalog

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(f"{BASE_URL}/models", headers=ATTRIBUTION)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            if cls._catalog:
                return cls._catalog  # stale beats empty
            raise ProviderError(f"Could not reach OpenRouter: {exc}") from exc

        models = []
        for entry in payload.get("data") or []:
            model_id = entry.get("id")
            if not model_id:
                continue
            pricing = entry.get("pricing") or {}
            arch = entry.get("architecture") or {}
            top = entry.get("top_provider") or {}

            # Orchestra drives text conversations, so a model that cannot emit
            # text is useless to an agent. No model in the catalog fails this
            # today — even the audio models declare text output — so it is a
            # forward guard against pure image/audio entries, not a live filter.
            if "text" not in (arch.get("output_modalities") or ["text"]):
                continue

            models.append(
                {
                    "id": model_id,
                    "name": entry.get("name") or model_id,
                    "vendor": model_id.split("/")[0],
                    "description": (entry.get("description") or "")[:400],
                    "context": entry.get("context_length") or top.get("context_length"),
                    "max_output": top.get("max_completion_tokens"),
                    "prompt_price": _per_million(pricing.get("prompt")),
                    "completion_price": _per_million(pricing.get("completion")),
                    # Only the `:free` suffix is authoritative. A zero token
                    # price elsewhere means token pricing does not apply to that
                    # model, not that using it costs nothing.
                    "free": model_id.endswith(":free"),
                    "modality": arch.get("modality") or "text->text",
                    "input_modalities": arch.get("input_modalities") or ["text"],
                    "moderated": bool(top.get("is_moderated")),
                    "reasoning": bool(entry.get("reasoning")),
                    "created": entry.get("created"),
                }
            )

        models.sort(key=lambda m: (m["vendor"].lower(), m["name"].lower()))
        cls._catalog, cls._fetched_at = models, time.time()
        return models

    async def search(
        self,
        query: str = "",
        free_only: bool = False,
        vision_only: bool = False,
        limit: int = 60,
    ) -> dict[str, Any]:
        models = await self.catalog()
        needle = query.strip().lower()

        matches = []
        for model in models:
            if free_only and not model["free"]:
                continue
            if vision_only and "image" not in model["input_modalities"]:
                continue
            if needle and needle not in f"{model['id']} {model['name']} {model['description']}".lower():
                continue
            matches.append(model)

        starred = set(self.starred)
        # Starred first so the models you actually use don't drift down the page.
        matches.sort(key=lambda m: (m["id"] not in starred, m["vendor"].lower(), m["name"].lower()))
        return {
            "total": len(models),
            "matched": len(matches),
            "models": [{**m, "starred": m["id"] in starred} for m in matches[:limit]],
        }

    async def status(self) -> Status:
        if not self.configured():
            return Status(
                state="not_configured",
                detail="Add an OpenRouter key to reach several hundred hosted models with one account.",
            )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{BASE_URL}/key", headers=self._headers())
            if resp.status_code == 401:
                return Status(state="error", detail="OpenRouter rejected the API key.")
            resp.raise_for_status()
            data = (resp.json() or {}).get("data") or {}
        except httpx.HTTPError as exc:
            return Status(state="unreachable", detail=f"Could not reach OpenRouter: {exc}")

        usage = data.get("usage")
        limit = data.get("limit")
        bits = [f"{len(self.starred)} model(s) starred"]
        if isinstance(usage, (int, float)):
            spent = f"${usage:.2f} used"
            bits.append(f"{spent} of ${limit:.2f}" if isinstance(limit, (int, float)) else spent)
        elif limit is None:
            bits.append("no spend limit set")
        if data.get("is_free_tier"):
            bits.append("free tier")
        return Status(state="ok", detail=" · ".join(bits), models=len(self.starred))

    async def list_models(self) -> list[ModelInfo]:
        """Starred models only — this feeds the pickers, not the browser."""
        if not self.configured() or not self.starred:
            return []
        try:
            catalog = {m["id"]: m for m in await self.catalog()}
        except ProviderError:
            catalog = {}

        models = []
        for model_id in self.starred:
            entry = catalog.get(model_id)
            if entry:
                price = "free" if entry["free"] else f"${entry['prompt_price']:.2f}/M in"
                models.append(
                    ModelInfo(
                        id=model_id,
                        provider=self.id,
                        label=entry["name"],
                        context=entry["context"],
                        detail=price,
                    )
                )
            else:
                # Hand-entered id the catalog does not know: still usable.
                models.append(
                    ModelInfo(id=model_id, provider=self.id, label=model_id, detail="custom id")
                )
        return models

    # -- chat -------------------------------------------------------------

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
            raise ProviderError("No OpenRouter API key configured.")

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

        try:
            async for chunk in self._stream(payload):
                yield chunk
        except _RetryWithoutSchema:
            # OpenRouter routes to hundreds of backends; not all honour
            # structured output. Retry plain and let the caller's repair path
            # handle the JSON.
            payload.pop("response_format", None)
            async for chunk in self._stream(payload):
                yield chunk

    async def _stream(self, payload: dict[str, Any]) -> AsyncIterator[Chunk]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0)) as client:
                async with client.stream(
                    "POST", f"{BASE_URL}/chat/completions", headers=self._headers(), json=payload
                ) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode(errors="replace")
                        if resp.status_code == 404 and "response_format" in payload:
                            raise _RetryWithoutSchema()
                        if resp.status_code == 400 and "response_format" in body and "response_format" in payload:
                            raise _RetryWithoutSchema()
                        raise ProviderError(_explain(resp.status_code, body, payload.get("model", "")))

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

                        if event.get("error"):
                            raise ProviderError(f"OpenRouter: {event['error'].get('message', event['error'])}")

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
            raise ProviderError(f"OpenRouter request failed: {exc}") from exc


class _RetryWithoutSchema(Exception):
    """This route does not accept response_format."""


def _explain(status: int, body: str, model: str) -> str:
    """OpenRouter's failures have specific, actionable causes — name them."""
    lowered = body.lower()
    if status == 402 or "insufficient" in lowered or "credit" in lowered:
        return "OpenRouter says the account is out of credit. Top up, or star a model tagged free."
    if status == 401:
        return "OpenRouter rejected the API key."
    if status == 404:
        return f"OpenRouter has no model called '{model}'. Check the id in the Models tab."
    if status == 429:
        return "OpenRouter rate-limited this request. Free models have tight limits — wait, or use a paid one."
    if "moderation" in lowered or status == 403:
        return "OpenRouter's moderation refused this request for the chosen model."
    return f"OpenRouter returned {status}: {body[:300]}"


def _per_million(raw: Any) -> float:
    """Prices arrive as dollars per token; per-million is the readable unit."""
    try:
        return round(float(raw) * 1_000_000, 4)
    except (TypeError, ValueError):
        return 0.0


