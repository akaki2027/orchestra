"""The big agent: turns one message into a task DAG over your sub-agents.

Three levels of enforcement, in order of preference:

  1. Provider-native constrained output (Anthropic output_config.format,
     Ollama format, OpenAI response_format) — the plan is valid by construction.
  2. Schema-in-prompt, extract the JSON, and one repair retry.
  3. Give up on planning and answer directly with the big agent.

A planner that 500s because a small local model emitted slightly-off JSON would
make the whole product feel broken, so every step degrades instead of failing.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .providers import build
from .providers.base import Msg, Provider, ProviderError

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Short unique id, e.g. t1"},
                    "agent": {"type": "string", "description": "id of the agent to run this"},
                    "instruction": {
                        "type": "string",
                        "description": "Self-contained subtask for that agent",
                    },
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Task ids whose output this needs. Empty means it can start immediately.",
                    },
                },
                "required": ["id", "agent", "instruction", "depends_on"],
                "additionalProperties": False,
            },
        },
        "synthesis": {
            "type": "string",
            "description": "How to combine the task results into the final answer",
        },
    },
    "required": ["tasks", "synthesis"],
    "additionalProperties": False,
}

PLANNER_SYSTEM = """You are the orchestrator. You receive a request and a roster of specialist \
sub-agents, and you break the request into subtasks routed to those agents.

Rules:
- Use only agent ids from the roster. Never invent one.
- Prefer parallelism. Give a task an empty `depends_on` unless it genuinely needs \
another task's output — independent tasks run simultaneously, so unnecessary \
dependencies just make the run slower.
- Each `instruction` must stand alone. The agent running it sees only its own \
instruction and the outputs it depends on, not this plan or the conversation.
- Keep the plan as small as the request allows. One task is a fine plan for a \
simple request. Do not manufacture work to use every agent.
- `synthesis` tells the final step how to combine the results.

Return only the plan object."""

MAX_TASKS = 24


class Plan:
    def __init__(self, tasks: list[dict[str, Any]], synthesis: str) -> None:
        self.tasks = tasks
        self.synthesis = synthesis

    def as_dict(self) -> dict[str, Any]:
        return {"tasks": self.tasks, "synthesis": self.synthesis}


class PlanningFailed(RuntimeError):
    """The big agent could not produce a usable plan; caller should answer directly."""


def roster(agents: list[dict[str, Any]]) -> str:
    """The routing table the big agent reads.

    Capabilities belong here, not just roles. A grant the planner cannot see is
    a grant it cannot route to: with the filesystem tool on one agent and no
    mention of it in the roster, "read this file and list what it contains"
    went to an agent that had no way to open anything.
    """
    lines = []
    for agent in agents:
        caps = []
        if (agent.get("capabilities") or {}).get("research"):
            caps.append("can search the web")
        for grant in agent.get("tools") or []:
            if grant == "filesystem":
                caps.append("can read and search files in the workspace folder")
            elif grant.startswith("mcp:"):
                caps.append(f"can use the {grant[4:]} tools")
        suffix = f" ({', '.join(caps)})" if caps else ""
        lines.append(f"- {agent['id']}: {agent.get('name') or agent['id']} — {agent['role']}{suffix}")
    return "\n".join(lines)


async def make_plan(
    provider_id: str,
    model: str,
    request: str,
    agents: list[dict[str, Any]],
    history: list[Msg] | None = None,
) -> Plan:
    """Ask the big agent for a DAG. Raises PlanningFailed if it can't produce one."""
    if not agents:
        raise PlanningFailed("No runnable sub-agents are configured.")

    provider: Provider = build(provider_id)
    prompt = (
        f"Available agents:\n{roster(agents)}\n\n"
        f"Request:\n{request}\n\n"
        "Produce the plan."
    )
    messages = [*(history or []), Msg(role="user", content=prompt)]

    if provider.caps.json_schema:
        try:
            raw = await _collect(provider, model, messages, json_schema=PLAN_SCHEMA)
            return validate(_loads(raw), agents)
        except (ProviderError, ValueError):
            # Fall through to the prompt-based path: some OpenAI-compatible
            # servers advertise schema support they do not actually honour.
            pass

    schema_text = json.dumps(PLAN_SCHEMA, indent=2)
    nudge = (
        f"{prompt}\n\nRespond with JSON only — no prose, no code fences — "
        f"matching this schema:\n{schema_text}"
    )
    raw = await _collect(provider, model, [Msg(role="user", content=nudge)])
    try:
        return validate(_loads(raw), agents)
    except ValueError as first_error:
        repair = (
            f"{nudge}\n\nYour previous reply could not be used: {first_error}\n"
            f"Previous reply:\n{raw[:2000]}\n\nReturn corrected JSON only."
        )
        try:
            raw = await _collect(provider, model, [Msg(role="user", content=repair)])
            return validate(_loads(raw), agents)
        except (ValueError, ProviderError) as exc:
            raise PlanningFailed(str(exc)) from exc


async def _collect(
    provider: Provider,
    model: str,
    messages: list[Msg],
    json_schema: dict[str, Any] | None = None,
) -> str:
    parts: list[str] = []
    async for chunk in provider.chat(
        model,
        messages,
        system=PLANNER_SYSTEM,
        json_schema=json_schema,
        max_tokens=8192,
    ):
        if chunk.type == "text":
            parts.append(chunk.text)
    return "".join(parts).strip()


def _loads(raw: str) -> dict[str, Any]:
    """Parse a plan out of a model reply that may be wrapped in prose or fences."""
    if not raw:
        raise ValueError("the reply was empty")

    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Last resort: the outermost brace pair.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object was found in the reply") from None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"the JSON did not parse ({exc.msg})") from exc

    if not isinstance(parsed, dict):
        raise ValueError("the reply was not a JSON object")
    return parsed


def validate(parsed: dict[str, Any], agents: list[dict[str, Any]]) -> Plan:
    """Check the plan is runnable, repairing what is safely repairable."""
    known = {agent["id"] for agent in agents}
    raw_tasks = parsed.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("the plan contained no tasks")
    if len(raw_tasks) > MAX_TASKS:
        raise ValueError(f"the plan had {len(raw_tasks)} tasks; the limit is {MAX_TASKS}")

    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_tasks):
        if not isinstance(item, dict):
            raise ValueError("a task was not an object")
        task_id = str(item.get("id") or f"t{index + 1}").strip()
        if task_id in seen:
            task_id = f"{task_id}_{index + 1}"
        seen.add(task_id)

        agent_id = str(item.get("agent") or "").strip()
        if agent_id not in known:
            raise ValueError(f"task {task_id} routes to unknown agent '{agent_id}'")

        instruction = str(item.get("instruction") or "").strip()
        if not instruction:
            raise ValueError(f"task {task_id} has no instruction")

        depends = item.get("depends_on") or []
        if not isinstance(depends, list):
            depends = []

        tasks.append(
            {
                "id": task_id,
                "agent": agent_id,
                "instruction": instruction,
                "depends_on": [str(d).strip() for d in depends if str(d).strip()],
            }
        )

    ids = {task["id"] for task in tasks}
    for task in tasks:
        # Drop dangling references rather than rejecting the whole plan — a
        # hallucinated dependency should not cost the user a replan.
        task["depends_on"] = [d for d in task["depends_on"] if d in ids and d != task["id"]]

    _assert_acyclic(tasks)

    synthesis = str(parsed.get("synthesis") or "").strip()
    if not synthesis:
        synthesis = "Combine the results into one clear answer to the original request."

    return Plan(tasks, synthesis)


def _assert_acyclic(tasks: list[dict[str, Any]]) -> None:
    pending = {task["id"]: set(task["depends_on"]) for task in tasks}
    resolved: set[str] = set()
    while pending:
        ready = [tid for tid, deps in pending.items() if deps <= resolved]
        if not ready:
            raise ValueError(
                "the plan's dependencies form a cycle: " + ", ".join(sorted(pending))
            )
        for tid in ready:
            resolved.add(tid)
            del pending[tid]
