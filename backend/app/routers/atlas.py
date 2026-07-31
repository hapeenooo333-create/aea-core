"""Atlas router for AEA Core CEO AI mission orchestration."""

from __future__ import annotations

import logging
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
    goal: str
    target_products: int | None = None
    target_pins: int | None = None
    campaign_name: str | None = None


class MissionCreateResponse(BaseModel):
    """Response payload returned after creating a mission."""

    mission_id: str | None = None
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
    target_products: int | None = None
    target_pins: int | None = None
    campaign_name: str | None = None
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
    }

    # The deployed Supabase instance currently exposes the earlier missions schema.
    # Keep the payload minimal so new Atlas requests still succeed there.
    return payload


def _get_steps_for_goal(goal: str) -> list[dict[str, str]]:
    """Return the ordered step sequence for a mission goal."""

    normalized_goal = goal.lower()
    if "affiliate" in normalized_goal or "campaign" in normalized_goal:
        return [
            {"step_name": "Research Worker", "worker_role": "Research Worker"},
            {"step_name": "Content Worker", "worker_role": "Content Worker"},
            {"step_name": "Pinterest Worker", "worker_role": "Pinterest Worker"},
            {"step_name": "Analytics Worker", "worker_role": "Analytics Worker"},
        ]
    return [{"step_name": "Research Worker", "worker_role": "Research Worker"}]


@router.post("/mission", response_model=MissionCreateResponse)
async def create_mission(request: MissionCreateRequest) -> MissionCreateResponse:
    """Create a mission in Supabase and seed the first Atlas workflow steps."""

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

        generated_steps = _get_steps_for_goal(request.goal)
        created_steps: list[dict[str, Any]] = []
        for step in generated_steps:
            step_payload = {
                "mission_id": mission_id,
                "step_name": step["step_name"],
                "worker_role": step["worker_role"],
                "status": "pending",
            }
            try:
                step_response = client.table("mission_steps").insert(step_payload).execute()
                step_rows = step_response.data or []
                if step_rows:
                    created_steps.append(step_rows[0])
            except Exception:
                logger.info("mission_steps table is unavailable; skipping step creation")

        first_step = created_steps[0] if created_steps else None
        first_command_payload: dict[str, Any] = {
            "command_type": "START_RESEARCH",
            "target_worker": first_step.get("worker_role") if first_step else None,
            "mission_id": mission_id,
            "payload": {"goal": request.goal, "step_name": first_step.get("step_name") if first_step else None},
            "status": "queued",
        }
        try:
            command_response = client.table("atlas_commands").insert(first_command_payload).execute()
            command_rows = command_response.data or []
            first_command = command_rows[0] if command_rows else None
        except Exception:
            logger.info("atlas_commands table is unavailable; skipping command creation")
            first_command = None

        return MissionCreateResponse(
            mission_id=mission_id,
            steps=created_steps,
            first_command=first_command,
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive error path
        error_message = _format_supabase_error(exc)
        logger.exception("Failed to create Atlas mission: %s", error_message)
        raise HTTPException(status_code=500, detail=f"Failed to create mission: {error_message}") from exc


@router.get("/missions", response_model=list[MissionDetailResponse])
async def list_missions() -> list[MissionDetailResponse]:
    """Return all missions with their associated mission steps."""

    client = database_module.supabase_client
    if not client:
        raise HTTPException(status_code=500, detail="Supabase client unavailable")

    try:
        missions_response = client.table("missions").select("*").execute()
        mission_rows = missions_response.data or []
        steps_response = client.table("mission_steps").select("*").execute()
        step_rows = steps_response.data or []

        steps_by_mission: dict[str, list[MissionStepResponse]] = {}
        for step in step_rows:
            mission_id = step.get("mission_id")
            if mission_id is None:
                continue
            steps_by_mission.setdefault(str(mission_id), []).append(MissionStepResponse(**step))

        missions: list[MissionDetailResponse] = []
        for mission in mission_rows:
            mission_id = mission.get("id")
            missions.append(
                MissionDetailResponse(
                    **mission,
                    steps=steps_by_mission.get(str(mission_id), []),
                )
            )
        return missions
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch missions") from exc


@router.get("/missions/{mission_id}", response_model=MissionDetailResponse)
async def get_mission(mission_id: str) -> MissionDetailResponse:
    """Return a single mission together with its steps."""

    client = database_module.supabase_client
    if not client:
        raise HTTPException(status_code=500, detail="Supabase client unavailable")

    try:
        mission_response = client.table("missions").select("*").execute()
        mission_rows = mission_response.data or []
        mission = next((row for row in mission_rows if str(row.get("id")) == mission_id), None)
        if mission is None:
            raise HTTPException(status_code=404, detail="Mission not found")

        steps_response = client.table("mission_steps").select("*").execute()
        step_rows = steps_response.data or []
        steps = [MissionStepResponse(**step) for step in step_rows if str(step.get("mission_id")) == mission_id]
        return MissionDetailResponse(**mission, steps=steps)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch mission") from exc


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
