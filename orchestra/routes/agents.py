"""Sub-agent CRUD."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from .. import agents as store

router = APIRouter(tags=["agents"])


@router.get("/agents")
async def list_agents() -> dict[str, Any]:
    return {
        "agents": [
            {**agent, "ready": store.is_ready(agent)} for agent in store.list_agents()
        ]
    }


@router.put("/agents/{agent_id}")
async def upsert_agent(agent_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    payload = {**payload, "id": agent_id}
    try:
        agent = store.save(payload)
    except store.AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**agent, "ready": store.is_ready(agent)}


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str) -> dict[str, Any]:
    try:
        removed = store.delete(agent_id)
    except store.AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="No such agent.")
    return {"deleted": agent_id}
