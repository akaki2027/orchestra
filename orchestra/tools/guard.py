"""The second egress choke point.

A hosted MCP server is someone else's machine. Sending it a tool call is the
same act as sending a hosted model a prompt, so it goes through the same policy,
raises the same `BlockedEgress` in strict mode, and lands on the same
declaration as its own row. Anything less would mean the receipt says "nothing
left this machine" while a tool quietly posted the file you just read to an
endpoint.

Same shape as `providers/guard.py` and for the same reason: the guarantee is a
property of the only object callers can get a tool from, not a call they have to
remember to make. `registry.build_for()` is that door.
"""

from __future__ import annotations

import json
from typing import Any

from .. import privacy
from .base import ToolResult, ToolSpec


class GuardedTool:
    """Applies the privacy policy to arguments leaving for a remote tool."""

    def __init__(self, inner: Any, policy: privacy.Policy) -> None:
        self._inner = inner
        self._policy = policy

    @property
    def spec(self) -> ToolSpec:
        return self._inner.spec

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        spec = self._inner.spec
        ledger = privacy.current_ledger()
        local = spec.reach == "local"
        outbound = json.dumps(arguments or {}, ensure_ascii=False)

        # A local tool touches nothing but this machine. Still recorded: "6 of 8
        # calls never left" is only provable if the ones that stayed are counted.
        if local or not self._policy.active:
            if ledger is not None:
                ledger.record(privacy.Egress(
                    provider=spec.source,
                    model=spec.name,
                    destination="local" if local else "remote",
                    chars=len(outbound),
                    note="tool" if local else "tool / privacy mode off",
                ))
            return await self._inner.call(arguments)

        findings = privacy.scan(outbound, self._policy.categories)

        if findings and self._policy.mode == "strict":
            categories = sorted({f.category for f in findings})
            if ledger is not None:
                ledger.record(privacy.Egress(
                    provider=spec.source,
                    model=spec.name,
                    destination="remote",
                    chars=0,
                    redacted={c: sum(1 for f in findings if f.category == c) for c in categories},
                    blocked=True,
                    note="tool blocked by strict mode",
                ))
            raise privacy.BlockedEgress(spec.name, categories)

        mapping = ledger.mapping if ledger is not None else {}
        counts: dict[str, int] = {}
        safe: dict[str, Any] = {}

        # Only string leaves can carry an email or a key, and rebuilding the
        # object preserves the schema the server is expecting.
        def scrub(value: Any) -> Any:
            nonlocal mapping
            if isinstance(value, str):
                result = privacy.redact(value, self._policy.categories, mapping)
                mapping = result.mapping
                for key, count in result.counts.items():
                    counts[key] = counts.get(key, 0) + count
                return result.text
            if isinstance(value, dict):
                return {k: scrub(v) for k, v in value.items()}
            if isinstance(value, list):
                return [scrub(v) for v in value]
            return value

        for key, value in (arguments or {}).items():
            safe[key] = scrub(value)

        if ledger is not None:
            ledger.mapping.update(mapping)
            ledger.record(privacy.Egress(
                provider=spec.source,
                model=spec.name,
                destination="remote",
                chars=len(json.dumps(safe, ensure_ascii=False)),
                redacted=counts,
                note="tool / redacted before sending" if counts else "tool",
            ))

        return await self._inner.call(safe)


def guarded(tool: Any, policy: privacy.Policy) -> GuardedTool:
    return GuardedTool(tool, policy)
