"""Orchestrated runs: plan with the big agent, fan out to sub-agents, synthesize."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse

from .. import agents as agent_store
from .. import config, planner, privacy, runner
from ..providers import build
from ..providers.base import Msg, ProviderError
from .chat import SSE_HEADERS, sse

router = APIRouter(tags=["runs"])


@router.post("/run")
async def run(payload: dict[str, Any] = Body(...)) -> StreamingResponse:
    request_text = (payload.get("message") or "").strip()
    cfg = config.load()

    orchestrator = {
        "provider": (payload.get("provider") or cfg["orchestrator"].get("provider") or "").strip(),
        "model": (payload.get("model") or cfg["orchestrator"].get("model") or "").strip(),
    }

    selected = payload.get("agents")
    mode = payload.get("mode") or "auto"

    async def events():
        # Installed before planning, not inside the Run: the planner's call to
        # the big agent carries the user's raw request, and for the recommended
        # setup (strongest model as orchestrator) that call is the one most
        # likely to leave the machine. It belongs on the declaration.
        ledger = privacy.Ledger(privacy.Policy.from_config(cfg))
        token = privacy.use_ledger(ledger)
        try:
            async for event in _events(ledger):
                yield event
        finally:
            privacy.reset_ledger(token)

    async def _events(ledger: privacy.Ledger):
        # Local copy: planning may move the big agent to a local model, and
        # rebinding the enclosing name would unbind every read before it.
        chief = dict(orchestrator)

        if not request_text:
            yield sse({"type": "error", "message": "Nothing to send."})
            return
        if not chief["provider"] or not chief["model"]:
            yield sse({"type": "error", "message": "Choose a model for the big agent first."})
            return

        # Only agents with a model assigned are runnable, so the planner is
        # never offered a route it cannot take.
        available = [a for a in agent_store.list_agents() if agent_store.is_ready(a)]
        if isinstance(selected, list) and selected:
            available = [a for a in available if a["id"] in set(selected)]

        if not available:
            yield sse(
                {
                    "type": "error",
                    "message": "No runnable sub-agents. Give at least one agent a model "
                    "in the Agents tab, or use Direct mode.",
                }
            )
            return

        by_id = {a["id"]: a for a in available}

        if mode == "manual":
            # A hand-wired pipeline is just a linear DAG, so it runs through the
            # same executor and emits the same events.
            order = selected if isinstance(selected, list) else [a["id"] for a in available]
            tasks = []
            previous: list[str] = []
            for index, agent_id in enumerate(order):
                if agent_id not in by_id:
                    continue
                task_id = f"t{index + 1}"
                tasks.append(
                    {
                        "id": task_id,
                        "agent": agent_id,
                        "instruction": request_text,
                        "depends_on": list(previous),
                    }
                )
                previous = [task_id]
            if not tasks:
                yield sse({"type": "error", "message": "The pipeline has no runnable steps."})
                return
            plan = planner.Plan(tasks, "Combine the results into one clear answer.")
        else:
            try:
                plan = await planner.make_plan(
                    chief["provider"], chief["model"], request_text, available
                )
            except privacy.BlockedEgress as blocked:
                # Strict mode refused to send the request to a hosted big agent.
                # This is neither a PlanningFailed nor a ProviderError, so it used
                # to escape the generator and kill the stream with zero events —
                # the user saw nothing at all. Reroute planning the same way the
                # runner reroutes a blocked sub-agent.
                local = await runner.find_local_model(privacy.Policy.from_config(cfg))
                if not local:
                    yield sse({"type": "error", "message": (
                        f"{blocked} No local model is available to plan with, so there is "
                        "nowhere to move this step. Install a local model, or switch the "
                        "border policy to Redact."
                    )})
                    return
                yield sse({"type": "planner_rerouted", "from": chief["model"],
                           "to": local["model"], "categories": blocked.categories})
                chief = dict(local)
                try:
                    plan = await planner.make_plan(
                        chief["provider"], chief["model"], request_text, available
                    )
                except (planner.PlanningFailed, ProviderError, privacy.BlockedEgress) as exc:
                    yield sse({"type": "error", "message": f"Planning failed after rerouting: {exc}"})
                    return
            except (planner.PlanningFailed, ProviderError) as exc:
                # Planning failed — answer directly rather than dead-ending.
                yield sse({"type": "plan_failed", "message": str(exc)})
                try:
                    provider = build(chief["provider"])
                    async for chunk in provider.chat(
                        chief["model"],
                        [Msg(role="user", content=request_text)],
                        max_tokens=8192,
                    ):
                        if chunk.type == "text":
                            yield sse({"type": "token", "text": chunk.text})
                    yield sse({"type": "done", "usage": {},
                               "privacy": ledger.summary(), "restore": ledger.mapping})
                except ProviderError as inner:
                    yield sse({"type": "error", "message": str(inner)})
                return

        execution = runner.Run(plan, by_id, request_text, chief, cfg, ledger=ledger)
        async for event in execution.stream():
            yield sse(event)

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)
