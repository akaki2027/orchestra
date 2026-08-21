#!/usr/bin/env python3
"""A full orchestrated run with every model call recorded verbatim.

Not a mock. This drives the same `planner.make_plan` and `runner.Run` the HTTP
route drives; the only addition is a tracing wrapper placed around whatever
`build()` returns, so every call the system makes -- planner, each sub-agent,
synthesis -- is captured with its exact system prompt, exact user prompt, and
exact reply.

Usage:  PYTHONPATH=. .venv/bin/python scripts/trace_run.py "your request"
"""
from __future__ import annotations

import asyncio
import sys
import time
from typing import Any

from orchestra import agents as agent_store
from orchestra import config, planner, privacy, runner
from orchestra.providers import build as real_build
from orchestra.providers.base import Chunk, Msg

CALLS: list[dict[str, Any]] = []
T0 = time.time()


def clip(text: str, limit: int = 700) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + f"\n… [+{len(text) - limit} more chars]"


class Tracer:
    """Wraps a provider and records every chat call end to end."""

    def __init__(self, inner, label: str) -> None:
        self._inner, self._label = inner, label

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def caps(self):
        return self._inner.caps

    def is_local(self) -> bool:
        return self._inner.is_local()

    async def chat(self, model, messages, **kw):
        record = {
            "seq": len(CALLS) + 1,
            "role": self._label,
            "provider": self._inner.id,
            "model": model,
            "local": self._inner.is_local(),
            "system": kw.get("system") or "",
            "prompt": "\n\n".join(m.content for m in messages),
            "started": time.time() - T0,
            "output": "",
            "usage": {},
            "error": None,
        }
        CALLS.append(record)
        try:
            async for chunk in self._inner.chat(model, messages, **kw):
                if chunk.type == "text":
                    record["output"] += chunk.text
                elif chunk.type == "usage":
                    record["usage"] = chunk.data
                yield chunk
        except Exception as exc:                      # noqa: BLE001
            record["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            record["ended"] = time.time() - T0


def install(label_for) -> None:
    def traced(provider_id, cfg=None):
        return Tracer(real_build(provider_id, cfg) if cfg else real_build(provider_id),
                      label_for())
    runner.build = traced
    planner.build = traced


CURRENT = {"label": "?"}
install(lambda: CURRENT["label"])


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


async def main() -> int:
    request = sys.argv[1] if len(sys.argv) > 1 else (
        "Compare mutexes and semaphores, then write one short paragraph a "
        "beginner could follow."
    )
    cfg = config.load()
    orch = cfg["orchestrator"]
    if not orch.get("provider"):
        print("No orchestrator model configured. Set one on the Desk first.")
        return 2

    available = [a for a in agent_store.list_agents() if agent_store.is_ready(a)]
    rule("SETUP")
    print(f"request      : {request}")
    print(f"orchestrator : {orch['provider']}/{orch['model']}")
    print(f"privacy mode : {cfg['privacy']['mode']}")
    print(f"lanes        : {cfg['concurrency']}")
    print(f"agents ready : {len(available)}")
    for a in available:
        caps = a.get("capabilities") or {}
        flags = [k for k, v in caps.items() if v] + ([f"{len(a.get('tools') or [])} tools"] if a.get("tools") else [])
        print(f"   {a['id']:12} {a['model']['provider']}/{a['model']['model']:16} {a['role'][:44]}"
              + (f"  [{', '.join(flags)}]" if flags else ""))

    # Mirrors routes/runs.py exactly: the ledger records from before planning,
    # so the planner's call to the big agent lands on the declaration too.
    ledger = privacy.Ledger(privacy.Policy.from_config(cfg))
    ledger_token = privacy.use_ledger(ledger)

    # Optional second argument pins the route to one agent, which is exactly
    # what Fixed-route mode does. Useful for testing a downstream stage without
    # a weak local planner deciding where work goes.
    pinned = sys.argv[2] if len(sys.argv) > 2 else ""

    rule("STAGE 1 — PLANNING (the big agent decides the DAG)"
         if not pinned else f"STAGE 1 — FIXED ROUTE (pinned to '{pinned}')")
    CURRENT["label"] = "planner"
    t = time.time()
    if pinned:
        if pinned not in {a["id"] for a in available}:
            print(f"  no ready agent called {pinned!r}")
            return 2
        plan = planner.Plan(
            [{"id": "t1", "agent": pinned, "instruction": request, "depends_on": []}],
            "Report the result plainly.")
        print(f"  hand-wired: t1 -> {pinned}")
    else:
      try:
        plan = await planner.make_plan(orch["provider"], orch["model"], request, available)
      except Exception as exc:                        # noqa: BLE001
        print(f"  planning failed: {type(exc).__name__}: {exc}")
        return 1
    if not pinned:
        print(f"  planned in {time.time() - t:.1f}s -> {len(plan.tasks)} task(s)")
    for task in plan.tasks:
        dep = f" after {task['depends_on']}" if task["depends_on"] else " (no dependencies — starts immediately)"
        print(f"    {task['id']}  ->  {task['agent']}{dep}")
        print(f"          {clip(task['instruction'], 150)}")
    print(f"  synthesis plan: {clip(plan.synthesis, 200)}")

    rule("STAGE 2 — EXECUTION (events in real time)")
    CURRENT["label"] = "sub-agent"
    by_id = {a["id"]: a for a in available}
    run = runner.Run(plan, by_id, request, orch, cfg, ledger=ledger)

    spans, tokens, events = {}, {}, []
    async for ev in run.stream():
        events.append(ev["type"])
        kind = ev["type"]
        stamp = f"  {time.time() - T0:6.2f}s "
        if kind == "node_start":
            spans[ev["id"]] = {"start": time.time() - T0, "agent": ev["agent_name"],
                               "model": ev["model"], "lane": ev["lane"]}
            tokens[ev["id"]] = 0
            print(f"{stamp}START    {ev['id']}  {ev['agent_name']} on {ev['provider']}/{ev['model']}")
        elif kind == "node_waiting":
            print(f"{stamp}WAIT     {ev['id']}  blocked on {ev['depends_on']}")
        elif kind == "node_queued":
            print(f"{stamp}QUEUE    {ev['id']}  lane '{ev['lane']}' full at {ev['limit']}")
        elif kind == "node_token":
            tokens[ev["id"]] = tokens.get(ev["id"], 0) + 1
        elif kind == "node_tool":
            print(f"{stamp}TOOL     {ev['id']}  {ev.get('name')} ({ev.get('reach','?')})")
        elif kind == "node_tool_result":
            print(f"{stamp}TOOL<-   {ev['id']}  ok={ev.get('ok')}")
        elif kind == "node_rerouted":
            print(f"{stamp}REROUTE  {ev['id']}  {ev['from']} -> {ev['to']} ({ev['categories']})")
        elif kind == "node_done":
            spans[ev["id"]]["end"] = time.time() - T0
            print(f"{stamp}DONE     {ev['id']}  {tokens.get(ev['id'],0)} chunks, "
                  f"{len(ev['output'])} chars")
        elif kind == "node_error":
            spans.setdefault(ev["id"], {})["end"] = time.time() - T0
            print(f"{stamp}ERROR    {ev['id']}  {ev['message'][:70]}")
        elif kind == "synthesis_start":
            CURRENT["label"] = "synthesis"
            print(f"{stamp}SYNTH    orchestrator combining {len(spans)} result(s)")
        elif kind == "done":
            print(f"{stamp}COMPLETE usage={ev['usage']}")
            final = ev
        elif kind == "error":
            print(f"{stamp}FAILED   {ev['message'][:100]}")
            final = ev

    rule("STAGE 3 — OVERLAP (was the fan-out really simultaneous?)")
    if spans:
        end = max(s.get("end", 0) for s in spans.values()) or 1
        for nid in sorted(spans):
            s = spans[nid]
            a, b = int(52 * s["start"] / end), int(52 * s.get("end", 0) / end)
            print(f"  {nid:4} {s.get('agent','?')[:11]:11} {s.get('model','?')[:14]:14} "
                  f"{s['start']:5.2f}-{s.get('end',0):5.2f}s |{' ' * a}{'#' * max(1, b - a)}")
        pairs = [(i, j) for i in spans for j in spans if i < j
                 and spans[i]["start"] < spans[j].get("end", 0)
                 and spans[j]["start"] < spans[i].get("end", 0)]
        summed = sum(s.get("end", 0) - s["start"] for s in spans.values())
        print(f"\n  summed {summed:.1f}s   wall {end:.1f}s   speedup {summed/end:.2f}x   "
              f"overlapping pairs {len(pairs)}")

    rule("STAGE 4 — EVERY MODEL CALL, VERBATIM")
    for c in CALLS:
        print(f"\n--- call {c['seq']}: {c['role']} -> {c['provider']}/{c['model']} "
              f"({'INTERIOR/local' if c['local'] else 'EXTERIOR/hosted'})  "
              f"{c['started']:.2f}s -> {c.get('ended', 0):.2f}s ---")
        if c["system"]:
            print(f"  SYSTEM SENT ({len(c['system'])} chars):\n    "
                  + clip(c["system"], 500).replace("\n", "\n    "))
        print(f"  PROMPT SENT ({len(c['prompt'])} chars):\n    "
              + clip(c["prompt"], 700).replace("\n", "\n    "))
        if c["error"]:
            print(f"  ERROR: {c['error']}")
        else:
            print(f"  REPLY ({len(c['output'])} chars):\n    "
                  + clip(c["output"], 500).replace("\n", "\n    "))
        if c["usage"]:
            print(f"  USAGE: {c['usage']}")

    rule("STAGE 5 — THE DECLARATION (what left this machine)")
    summary = run.ledger.summary()
    for k in ("mode", "calls", "local_calls", "remote_calls", "remote_chars", "blocked",
              "redacted", "protected_values"):
        print(f"  {k:17} {summary.get(k)}")
    print("  rows:")
    for e in summary.get("entries", []):
        print(f"    {e.get('destination'):7} {e.get('provider'):12} {e.get('model','')[:26]:26} "
              f"{e.get('chars',0):6} chars  {e.get('note','')}")

    privacy.reset_ledger(ledger_token)

    rule("VERDICT")
    local_calls = [c for c in CALLS if c["local"]]
    remote_calls = [c for c in CALLS if not c["local"]]
    failed = [c for c in CALLS if c["error"]]
    print(f"  model calls made      : {len(CALLS)}  ({len(local_calls)} local, {len(remote_calls)} hosted)")
    print(f"  calls that failed     : {len(failed)}")
    print(f"  distinct models used  : {sorted({c['model'] for c in CALLS})}")
    print(f"  event types seen      : {sorted(set(events))}")
    # The ledger records tool calls alongside model calls; the tracer only sees
    # model calls. Compare like with like or this cries wolf on every tool run.
    entries = summary.get("entries", [])
    tool_rows = [e for e in entries if (e.get("note") or "").startswith("tool")]
    model_rows = len(entries) - len(tool_rows)
    print(f"  ledger rows           : {len(entries)}  ({model_rows} model + {len(tool_rows)} tool)")
    print(f"  every model call on the declaration: "
          f"{'YES' if model_rows == len(CALLS) else f'NO — {len(CALLS)} traced vs {model_rows} recorded'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
