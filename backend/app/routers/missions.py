"""Mission API routes for Sprint 6.0."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app import database as database_module
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.mission_engine import MissionEngine

router = APIRouter(prefix="/missions", tags=["missions"])
mission_engine = MissionEngine()
orchestrator = AgentOrchestrator()


class MissionCreateRequest(BaseModel):
    """Request payload for creating a mission."""

    title: str
    description: str | None = None
    worker_id: str | None = None
    priority: str | None = None

    model_config = ConfigDict(extra="allow")


def _status_code_for_error(error: str | None) -> int:
    """Translate a service-layer error into an HTTP status code."""

    if not error:
        return status.HTTP_500_INTERNAL_SERVER_ERROR

    message = error.lower()
    if "required" in message or "missing" in message:
        return status.HTTP_400_BAD_REQUEST
    if "not found" in message:
        return status.HTTP_404_NOT_FOUND
    if "unavailable" in message or "client" in message:
        return status.HTTP_503_SERVICE_UNAVAILABLE
    return status.HTTP_500_INTERNAL_SERVER_ERROR


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_mission(request: MissionCreateRequest) -> dict[str, Any]:
    """Create a mission and return the created record."""

    result = mission_engine.create_mission(
        title=request.title,
        description=request.description or "",
        worker_id=request.worker_id,
        priority=request.priority or "normal",
    )

    if not result.get("success"):
        error = result.get("error") or "Failed to create mission"
        raise HTTPException(status_code=_status_code_for_error(str(error)), detail=str(error))

    mission = result.get("mission") or {}
    return {"success": True, "mission": mission}


@router.get("")
async def list_missions() -> list[dict[str, Any]]:
    """Return all mission records."""

    client = database_module.supabase_client
    if not client:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Supabase client unavailable")

    try:
        response = client.table("missions").select("*").execute()
        rows = response.data or []
        return [dict(row) for row in rows]
    except Exception as exc:  # pragma: no cover - defensive error path
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch missions") from exc


@router.get("/{mission_id}")
async def get_mission(mission_id: str) -> dict[str, Any]:
    """Return one mission by identifier."""

    mission = mission_engine.get_mission(mission_id)
    if mission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found")
    return mission


@router.post("/{mission_id}/run")
async def run_mission(mission_id: str) -> dict[str, Any]:
    """Execute a mission through the orchestrator."""

    result = orchestrator.run_mission(mission_id)
    if not result.get("success"):
        error = result.get("error") or "Mission execution failed"
        raise HTTPException(status_code=_status_code_for_error(str(error)), detail=str(error))
    return result
