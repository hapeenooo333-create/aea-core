"""Atlas router for AEA Core CEO AI mission orchestration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app import database as database_module

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/atlas", tags=["atlas"])

VALID_COMMAND_TYPES = (
    "CREATE_MISSION",
    "START_RESEARCH",
    "START_CONTENT",
    "START_PUBLISH",
    "START_ANALYTICS",
    "PAUSE",
    "RESUME",
    "RETRY",
)


class MissionCreateRequest(BaseModel):
    """Request body for creating a new Atlas mission."""

    title: str
    description: str | None = None
    assigned_worker: str | None = None
    priority: str | None = None
    status: str | None = None
    progress: int | None = None
    result: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")


class MissionPatchRequest(BaseModel):
    """Request body for updating an existing Atlas mission."""

    status: str | None = None
    progress: int | None = None
    assigned_worker: str | None = None
    result: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")


class MissionCreateResponse(BaseModel):
    """Response payload returned after creating a mission."""

    id: str | int | None = None
    mission_id: str | int | None = None
    title: str | None = None
    description: str | None = None
    assigned_worker: str | None = None
    priority: str | None = None
    status: str | None = None
    progress: int | None = None
    result: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    steps: list[dict[str, Any]] | None = None
    first_command: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")


class AtlasCommandCreateRequest(BaseModel):
    """Request body for issuing a new command to a worker."""

    command_type: Literal[VALID_COMMAND_TYPES]  # type: ignore[arg-type]
    target_worker: str | None = None
    mission_id: str | None = None
    payload: dict[str, Any] | None = None


class AtlasCommandResponse(BaseModel):
    """Response payload for a created Atlas command."""

    id: str | None = None
    command_type: str | None = None
    target_worker: str | None = None
    mission_id: str | None = None
    payload: dict[str, Any] | None = None
    status: str | None = None
    created_at: str | None = None

    model_config = ConfigDict(extra="allow")


class MissionStepResponse(BaseModel):
    """Representation of a mission step."""

    id: str | None = None
    mission_id: str | None = None
    step_name: str | None = None
    worker_role: str | None = None
    status: str | None = None
    created_at: str | None = None

    model_config = ConfigDict(extra="allow")


class MissionDetailResponse(BaseModel):
    """Mission payload with nested steps."""

    id: str | None = None
    title: str | None = None
    description: str | None = None
    assigned_worker: str | None = None
    priority: str | None = None
    status: str | None = None
    progress: int | None = None
    result: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    steps: list[MissionStepResponse] | None = None

    model_config = ConfigDict(extra="allow")


class WorkerResponseRecord(BaseModel):
    """Worker response payload sent back to Atlas."""

    id: str | None = None
    response_type: str | None = None
    worker_id: str | None = None
    mission_id: str | None = None
    command_id: str | None = None
    payload: dict[str, Any] | None = None
    created_at: str | None = None

    model_config = ConfigDict(extra="allow")


def _format_supabase_error(exc: Exception) -> str:
    """Extract a readable error string from Supabase exceptions."""

    if hasattr(exc, "message") and exc.message:
        return str(exc.message)
    if hasattr(exc, "details") and exc.details:
        return str(exc.details)
    if hasattr(exc, "response"):
        response = getattr(exc, "response", None)
        if response is not None:
            text = getattr(response, "text", None) or getattr(response, "content", None)
            if text:
                return str(text)
    return str(exc)


def _build_mission_payload(request: MissionCreateRequest) -> dict[str, Any]:
    """Build a mission payload compatible with the current Supabase schema."""

    payload: dict[str, Any] = {
        "title": request.title,
        "description": request.description,
        "assigned_worker": request.assigned_worker,
        "priority": request.priority or "normal",
        "status": request.status or "pending",
        "progress": request.progress if request.progress is not None else 0,
        "result": request.result or {},
        "retry_count": 0,
    }
    return payload


def _build_mission_update_payload(request: MissionPatchRequest) -> dict[str, Any]:
    """Build a mission update payload from the allowed patch fields."""

    payload: dict[str, Any] = {}
    if request.status is not None:
        payload["status"] = request.status
    if request.progress is not None:
        payload["progress"] = request.progress
    if request.assigned_worker is not None:
        payload["assigned_worker"] = request.assigned_worker
    if request.result is not None:
        payload["result"] = request.result
    if not payload:
        raise HTTPException(status_code=400, detail="At least one valid field must be provided")
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    return payload


@router.post("/mission", response_model=MissionCreateResponse)
async def create_mission(request: MissionCreateRequest) -> MissionCreateResponse:
    """Create a mission in the missions table."""

    client = database_module.supabase_client
    if not client:
        raise HTTPException(status_code=500, detail="Supabase client unavailable")

    try:
        mission_payload = _build_mission_payload(request)
        mission_response = client.table("missions").insert(mission_payload).execute()
        mission_rows = mission_response.data or []
        if not mission_rows:
            raise HTTPException(status_code=500, detail="Mission creation returned no data")
        mission = mission_rows[0]
        mission_id = mission.get("id")
        response_payload = {"id": mission_id, "mission_id": mission_id, **mission}
        return MissionCreateResponse(**response_payload)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive error path
        error_message = _format_supabase_error(exc)
        logger.exception("Failed to create Atlas mission: %s", error_message)
        raise HTTPException(status_code=500, detail=f"Failed to create mission: {error_message}") from exc


@router.get("/missions", response_model=list[MissionDetailResponse])
async def list_missions() -> list[MissionDetailResponse]:
    """Return all missions ordered by created_at descending."""

    client = database_module.supabase_client
    if not client:
        raise HTTPException(status_code=500, detail="Supabase client unavailable")

    try:
        missions_response = client.table("missions").select("*").order("created_at", desc=True).execute()
        mission_rows = missions_response.data or []
        return [MissionDetailResponse(**mission) for mission in mission_rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch missions") from exc


@router.get("/missions/{mission_id}", response_model=MissionDetailResponse)
async def get_mission(mission_id: str) -> MissionDetailResponse:
    """Return a single mission."""

    client = database_module.supabase_client
    if not client:
        raise HTTPException(status_code=500, detail="Supabase client unavailable")

    try:
        mission_response = client.table("missions").select("*").execute()
        mission_rows = mission_response.data or []
        mission = next((row for row in mission_rows if str(row.get("id")) == mission_id), None)
        if mission is None:
            raise HTTPException(status_code=404, detail="Mission not found")
        return MissionDetailResponse(**mission)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch mission") from exc


@router.patch("/missions/{mission_id}", response_model=MissionDetailResponse)
async def patch_mission(mission_id: str, request: MissionPatchRequest) -> MissionDetailResponse:
    """Patch the mutable mission fields for an existing mission."""

    client = database_module.supabase_client
    if not client:
        raise HTTPException(status_code=500, detail="Supabase client unavailable")

    try:
        updates = _build_mission_update_payload(request)
        try:
            response = client.table("missions").update(updates).eq("id", mission_id).execute()
            rows = response.data or []
            if rows:
                mission = rows[0]
            else:
                mission = None
        except Exception:
            mission = None

        if mission is None:
            mission_rows_response = client.table("missions").select("*").execute()
            mission_rows = mission_rows_response.data or []
            mission = next((row for row in mission_rows if str(row.get("id")) == mission_id), None)
            if mission is None:
                raise HTTPException(status_code=404, detail="Mission not found")
            mission.update(updates)
            if hasattr(client, "data") and "missions" in client.data:
                for row in client.data["missions"]:
                    if str(row.get("id")) == mission_id:
                        row.update(updates)
                        break

        return MissionDetailResponse(**mission)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to update mission") from exc


@router.post("/command", response_model=AtlasCommandResponse)
async def create_command(request: AtlasCommandCreateRequest) -> AtlasCommandResponse:
    """Insert a new Atlas command into the command protocol table."""

    client = database_module.supabase_client
    if not client:
        raise HTTPException(status_code=500, detail="Supabase client unavailable")

    if request.command_type not in VALID_COMMAND_TYPES:
        raise HTTPException(status_code=400, detail="Invalid command type")

    try:
        payload: dict[str, Any] = {
            "command_type": request.command_type,
            "target_worker": request.target_worker,
            "mission_id": request.mission_id,
            "payload": request.payload or {},
            "status": "queued",
        }
        response = client.table("atlas_commands").insert(payload).execute()
        rows = response.data or []
        if not rows:
            raise HTTPException(status_code=500, detail="Command creation returned no data")
        return AtlasCommandResponse(**rows[0])
    except HTTPException:
        raise
    except Exception as exc:
        error_message = _format_supabase_error(exc)
        logger.exception("Failed to create Atlas command: %s", error_message)
        raise HTTPException(status_code=500, detail=f"Failed to create command: {error_message}") from exc


@router.get("/commands", response_model=list[AtlasCommandResponse])
async def list_commands() -> list[AtlasCommandResponse]:
    """Return all registered Atlas commands with their current status."""

    client = database_module.supabase_client
    if not client:
        raise HTTPException(status_code=500, detail="Supabase client unavailable")

    try:
        response = client.table("atlas_commands").select("*").execute()
        rows = response.data or []
        return [AtlasCommandResponse(**row) for row in rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch commands") from exc


@router.get("/worker-responses", response_model=list[WorkerResponseRecord])
async def list_worker_responses() -> list[WorkerResponseRecord]:
    """Return worker responses ordered from newest to oldest."""

    client = database_module.supabase_client
    if not client:
        raise HTTPException(status_code=500, detail="Supabase client unavailable")

    try:
        response = client.table("worker_responses").select("*").order("created_at", desc=True).execute()
        rows = response.data or []
        return [WorkerResponseRecord(**row) for row in rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch worker responses") from exc
