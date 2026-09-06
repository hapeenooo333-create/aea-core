"""Mission API routes for Sprint 6.0."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from app import database as database_module
from app.dependencies import get_current_user_id, get_user_scoped_client, verify_mission_ownership
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.mission_engine import MissionEngine

router = APIRouter(prefix="/missions", tags=["missions"])


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
async def create_mission(
    request: Request,
    body: MissionCreateRequest,
    current_user_id: str = Depends(get_current_user_id),
    client: Any = Depends(get_user_scoped_client),
) -> dict[str, Any]:
    """Create a mission for the current user."""

    mission_engine = MissionEngine(client=client)
    result = mission_engine.create_mission(
        title=body.title,
        description=body.description or "",
        worker_id=body.worker_id,
        priority=body.priority or "normal",
        owner_id=current_user_id,
        client=client,
    )

    if not result.get("success"):
        error = result.get("error") or "Failed to create mission"
        raise HTTPException(status_code=_status_code_for_error(str(error)), detail=str(error))

    mission = result.get("mission") or {}
    return {"success": True, "mission": mission}


@router.get("")
async def list_missions(
    request: Request,
    current_user_id: str = Depends(get_current_user_id),
    client: Any = Depends(get_user_scoped_client),
) -> list[dict[str, Any]]:
    """Return mission records owned by the current user."""

    mission_engine = MissionEngine(client=client)
    # Filter by owner_id, not assigned_worker
    if not client:
        return []
    try:
        response = client.table("missions").select("*").eq("owner_id", current_user_id).order("created_at", desc=True).limit(100).execute()
        rows = response.data or []
        return [MissionEngine._normalize_mission(row) for row in rows if MissionEngine._normalize_mission(row)]
    except Exception:  # pragma: no cover - defensive
        return []


@router.get("/{mission_id}")
async def get_mission(
    mission_id: str,
    mission: dict[str, Any] = Depends(verify_mission_ownership),
) -> dict[str, Any]:
    """Return one mission owned by the current user."""
    return mission


@router.post("/{mission_id}/run")
async def run_mission(
    request: Request,
    mission_id: str,
    mission: dict[str, Any] = Depends(verify_mission_ownership),
    current_user_id: str = Depends(get_current_user_id),
) -> dict[str, Any]:
    """Execute a mission owned by the current user."""

    orchestrator = AgentOrchestrator(owner_id=current_user_id)
    result = orchestrator.run_mission(mission_id)
    if not result.get("success"):
        error = result.get("error") or "Mission execution failed"
        raise HTTPException(status_code=_status_code_for_error(str(error)), detail=str(error))
    return result
