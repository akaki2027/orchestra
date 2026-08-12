"""Anthropic provider — hosted Claude models.

Models are listed live from the API rather than hardcoded, so the picker never
goes stale when new models ship. Research runs on Anthropic's own
infrastructure via the server-side web_search / web_fetch tools, which means an
Anthropic research agent needs no local sandbox at all.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from .base import Caps, Chunk, ModelInfo, Msg, ProviderError, Status

# Fallback list, used only when the live models endpoint is unreachable.
KNOWN_MODELS = [
    ("claude-opus-5", "Claude Opus 5"),
    ("claude-sonnet-5", "Claude Sonnet 5"),
    ("claude-haiku-4-5", "Claude Haiku 4.5"),
]

DEFAULT_MODEL = "claude-opus-5"

# Server-side research tools. These execute on Anthropic's infrastructure.
RESEARCH_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search"},
    {"type": "web_fetch_20260209", "name": "web_fetch"},
]

# A server-tool turn can stop with `pause_turn`; resend to resume. Bounded so a
# pathological loop cannot run forever.
MAX_RESUMES = 5


class AnthropicProvider:
    id = "anthropic"
    label = "Anthropic (Claude)"
    caps = Caps(json_schema=True, downloadable=False, server_side_research=True)

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or None

    def configured(self) -> bool:
        return bool(self.api_key)

    def is_local(self) -> bool:
        return False

    def _client(self):
        if not self.api_key:
            raise ProviderError("No Anthropic API key configured.")
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("The `anthropic` package is not installed.") from exc
        return AsyncAnthropic(api_key=self.api_key, max_retries=2)

    async def status(self) -> Status:
        if not self.configured():
            return Status(state="not_configured", detail="Add an API key to use Claude models.")
        try:
            models = await self.list_models()
        except ProviderError as exc:
            return Status(state="error", detail=str(exc))
        return Status(state="ok", detail=f"{len(models)} model(s) available", models=len(models))

    async def list_models(self) -> list[ModelInfo]:
        if not self.configured():
            return []
        client = self._client()
        try:
            entries = []
            page = await client.models.list()
            entries.extend(page.data)
            # The catalog is small; one page is the whole list in practice, but
            # follow the cursor if the SDK reports more.
            while getattr(page, "has_more", False):
                page = await client.models.list(after_id=page.data[-1].id)
                entries.extend(page.data)
        except Exception as exc:  # noqa: BLE001 - surfaced to the setup screen
            message = str(exc)
            if "authentication" in message.lower() or "401" in message:
                raise ProviderError("Anthropic rejected the API key.") from exc
            # Offline or endpoint unavailable: fall back to known IDs so the
            # picker still works.
            return [
                ModelInfo(id=mid, provider=self.id, label=label, detail="offline list")
                for mid, label in KNOWN_MODELS
            ]
        finally:
            await client.close()

        models = []
        for entry in entries:
            models.append(
                ModelInfo(
                    id=entry.id,
                    provider=self.id,
                    label=getattr(entry, "display_name", None) or entry.id,
                    context=getattr(entry, "max_input_tokens", None),
                    detail="hosted",
                )
            )
        return models

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
        client = self._client()

        kwargs: dict[str, Any] = {
            "model": model,
            # Headroom: thinking is on by default on current Opus models and
            # shares this budget with the visible response.
            "max_tokens": max(max_tokens, 4096),
            "messages": [m.as_dict() for m in messages],
        }
        if system:
            kwargs["system"] = system

        # `output_config` travels in extra_body so this works across SDK
        # versions regardless of whether the typed parameter exists yet.
        extra_body: dict[str, Any] = {}
        if json_schema is not None:
            extra_body["output_config"] = {
                "format": {"type": "json_schema", "schema": json_schema}
            }
        if extra_body:
            kwargs["extra_body"] = extra_body

        if tools and "research" in tools:
            kwargs["tools"] = RESEARCH_TOOLS

        # Sampling parameters are rejected on current Opus/Sonnet models, so
        # only send temperature where the model still accepts it.
        if temperature is not None and not _rejects_sampling(model):
            kwargs["temperature"] = temperature

        try:
            resumes = 0
            while True:
                async with client.messages.stream(**kwargs) as stream:
                    async for event in stream:
                        if event.type == "content_block_delta" and event.delta.type == "text_delta":
                            yield Chunk(type="text", text=event.delta.text)
                        elif event.type == "content_block_start":
                            block_type = getattr(event.content_block, "type", "")
                            if block_type == "server_tool_use":
                                yield Chunk(
                                    type="tool",
                                    data={"name": getattr(event.content_block, "name", "tool")},
                                )
                    final = await stream.get_final_message()

                usage = getattr(final, "usage", None)
                if usage is not None:
                    yield Chunk(
                        type="usage",
                        data={
                            "input_tokens": getattr(usage, "input_tokens", None),
                            "output_tokens": getattr(usage, "output_tokens", None),
                        },
                    )

                if final.stop_reason == "refusal":
                    raise ProviderError(
                        "Claude declined this request. Try rephrasing, or route this agent "
                        "to a different model."
                    )

                # A server-side tool hit its iteration limit — resend to resume.
                if final.stop_reason == "pause_turn" and resumes < MAX_RESUMES:
                    resumes += 1
                    kwargs["messages"] = [
                        *kwargs["messages"],
                        {"role": "assistant", "content": final.content},
                    ]
                    continue
                break
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Anthropic request failed: {exc}") from exc
        finally:
            await client.close()


def _rejects_sampling(model: str) -> bool:
    """Current Opus/Sonnet models return 400 for temperature/top_p/top_k."""
    model = model.lower()
    return (
        model.startswith("claude-opus-5")
        or model.startswith("claude-sonnet-5")
        or model.startswith("claude-fable")
        or model.startswith("claude-mythos")
        or model.startswith("claude-opus-4-7")
        or model.startswith("claude-opus-4-8")
    )
