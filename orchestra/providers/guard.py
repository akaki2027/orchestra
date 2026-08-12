"""The egress choke point.

Every provider the registry hands out is wrapped in this. That is the entire
design: the privacy guarantee is not a function call sites remember to make, it
is a property of the only object they can get a model from. New code paths,
future providers, and anything a contributor adds later are covered without
knowing this module exists.

If you are reviewing whether the claim in the README is true, this file and
`registry.build()` are the two places to read.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from .. import privacy
from .base import Chunk, Msg, ModelInfo, Provider, Status


class GuardedProvider:
    """Applies the privacy policy to anything leaving for a hosted model."""

    def __init__(self, inner: Provider, policy: privacy.Policy) -> None:
        self._inner = inner
        self._policy = policy

    # -- pass-through surface ---------------------------------------------

    @property
    def id(self) -> str:
        return self._inner.id

    @property
    def label(self) -> str:
        return self._inner.label

    @property
    def caps(self):
        return self._inner.caps

    def configured(self) -> bool:
        return self._inner.configured()

    def is_local(self) -> bool:
        return self._inner.is_local()

    async def status(self) -> Status:
        return await self._inner.status()

    async def list_models(self) -> list[ModelInfo]:
        return await self._inner.list_models()

    def __getattr__(self, name: str) -> Any:
        # Provider-specific extras (Ollama's pull/delete) stay reachable.
        return getattr(self._inner, name)

    # -- the guarded path --------------------------------------------------

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
        ledger = privacy.current_ledger()
        local = self._inner.is_local()
        outbound = (system or "") + "".join(m.content for m in messages)

        # A local model is on this machine, so there is nothing to protect it
        # from. Record the call anyway — "4 of 6 calls never left" is only
        # provable if the local ones are counted too.
        if local or not self._policy.active:
            if ledger is not None:
                ledger.record(
                    privacy.Egress(
                        provider=self._inner.id,
                        model=model,
                        destination="local" if local else "remote",
                        chars=len(outbound),
                        note="" if local else "privacy mode off",
                    )
                )
            async for chunk in self._inner.chat(
                model,
                messages,
                system=system,
                json_schema=json_schema,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
            ):
                yield chunk
            return

        findings = privacy.scan(outbound, self._policy.categories)

        if findings and self._policy.mode == "strict":
            categories = sorted({f.category for f in findings})
            if ledger is not None:
                ledger.record(
                    privacy.Egress(
                        provider=self._inner.id,
                        model=model,
                        destination="remote",
                        chars=0,
                        redacted={c: sum(1 for f in findings if f.category == c) for c in categories},
                        blocked=True,
                        note="blocked by strict mode",
                    )
                )
            raise privacy.BlockedEgress(self._inner.label, categories)

        mapping = ledger.mapping if ledger is not None else {}
        redacted_system = None
        counts: dict[str, int] = {}

        if system:
            result = privacy.redact(system, self._policy.categories, mapping)
            redacted_system = result.text
            mapping = result.mapping
            for key, value in result.counts.items():
                counts[key] = counts.get(key, 0) + value

        safe_messages: list[Msg] = []
        for message in messages:
            result = privacy.redact(message.content, self._policy.categories, mapping)
            mapping = result.mapping
            for key, value in result.counts.items():
                counts[key] = counts.get(key, 0) + value
            safe_messages.append(Msg(role=message.role, content=result.text))

        if ledger is not None:
            ledger.mapping.update(mapping)
            ledger.record(
                privacy.Egress(
                    provider=self._inner.id,
                    model=model,
                    destination="remote",
                    chars=len(redacted_system or "") + sum(len(m.content) for m in safe_messages),
                    redacted=counts,
                    note="redacted before sending" if counts else "",
                )
            )

        async for chunk in self._inner.chat(
            model,
            safe_messages,
            system=redacted_system if system else None,
            json_schema=json_schema,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
        ):
            yield chunk


def guarded(provider: Provider, policy: privacy.Policy) -> Provider:
    return GuardedProvider(provider, policy)
