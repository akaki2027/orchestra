"""Orchestrated runs: plan with the big agent, fan out to sub-agents, synthesize."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse

from .. import agents as agent_store
from .. import config, planner, runner
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
        if not request_text:
            yield sse({"type": "error", "message": "Nothing to send."})
            return
        if not orchestrator["provider"] or not orchestrator["model"]:
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
                    orchestrator["provider"], orchestrator["model"], request_text, available
                )
            except (planner.PlanningFailed, ProviderError) as exc:
                # Planning failed — answer directly rather than dead-ending.
                yield sse({"type": "plan_failed", "message": str(exc)})
                try:
                    provider = build(orchestrator["provider"])
                    async for chunk in provider.chat(
                        orchestrator["model"],
                        [Msg(role="user", content=request_text)],
                        max_tokens=8192,
                    ):
                        if chunk.type == "text":
                            yield sse({"type": "token", "text": chunk.text})
                    yield sse({"type": "done", "usage": {}})
                except ProviderError as inner:
                    yield sse({"type": "error", "message": str(inner)})
                return

        execution = runner.Run(plan, by_id, request_text, orchestrator, cfg)
        async for event in execution.stream():
            yield sse(event)

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)
