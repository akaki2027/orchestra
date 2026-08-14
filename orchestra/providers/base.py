"""The provider seam.

Everything above this layer — planner, runner, agents, UI — talks only to these
types. That is what makes any model slot swappable: a slot is just
`{"provider": "ollama", "model": "qwen2.5:7b"}`, and no code path outside
`providers/` knows which backend is behind it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Protocol, runtime_checkable

Role = Literal["user", "assistant"]


@dataclass
class Msg:
    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class ModelInfo:
    """One selectable model, as shown in a picker."""

    id: str
    provider: str
    label: str
    # Local models occupy disk and can be pulled/deleted; hosted ones cannot.
    local: bool = False
    context: int | None = None
    size_bytes: int | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "label": self.label,
            "local": self.local,
            "context": self.context,
            "size_bytes": self.size_bytes,
            "detail": self.detail,
        }


@dataclass
class Caps:
    """What a provider can do, so callers can degrade instead of failing."""

    # Native constrained JSON output. When False the planner falls back to
    # schema-in-prompt plus a repair retry.
    json_schema: bool = False
    # Models live on disk here and can be pulled/deleted from the portal.
    downloadable: bool = False
    # Web search/fetch runs on the provider's own infrastructure.
    server_side_research: bool = False


@dataclass
class Chunk:
    """One streamed event from a chat call."""

    type: Literal["text", "usage", "tool", "tool_result", "done"]
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Status:
    """Provider health, as rendered on the setup screen."""

    state: Literal["ok", "not_configured", "unreachable", "error"]
    detail: str = ""
    models: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"state": self.state, "detail": self.detail, "models": self.models}


class ProviderError(RuntimeError):
    """A provider failed in a way worth showing the user verbatim."""


@runtime_checkable
class Provider(Protocol):
    id: str
    label: str
    caps: Caps

    def configured(self) -> bool:
        """False when the user hasn't supplied what this provider needs yet."""
        ...

    def is_local(self) -> bool:
        """True only when inference happens on this machine or LAN.

        Deliberately a method, not a static flag: an Ollama pointed at a remote
        host is NOT local, and an OpenAI-compatible endpoint on localhost (LM
        Studio, vLLM) IS. Getting this backwards would silently break the
        privacy guarantee, so it is decided per configured instance.
        """
        ...

    async def status(self) -> Status:
        """Cheap reachability probe for the setup screen."""
        ...

    async def list_models(self) -> list[ModelInfo]:
        ...

    def chat(
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
        """Stream a completion. Implementations are async generators."""
        ...
