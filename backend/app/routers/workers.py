"""Worker API routes for Sprint 6.0."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app import database as database_module
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.worker_runtime import WorkerRuntime

router = APIRouter(prefix="/workers", tags=["workers"])
worker_runtime = WorkerRuntime()
orchestrator = AgentOrchestrator()


class WorkerCreateRequest(BaseModel):
    """Request payload for creating a worker."""

    name: str
    role: str | None = None
    status: str | None = None

    model_config = ConfigDict(extra="allow")


# Mock data for when Supabase is unavailable
MOCK_WORKERS = [
    {
        "id": "worker-atlas",
        "name": "Atlas",
        "role": "researcher",
        "status": "active",
    },
    {
        "id": "worker-sentinel",
        "name": "Sentinel",
        "role": "analyst",
        "status": "active",
    },
]


@router.get("")
async def list_workers() -> list[dict[str, Any]]:
    """Return all workers or mock data if Supabase is unavailable."""

    client = database_module.supabase_client
    if not client:
        return MOCK_WORKERS

    try:
        response = client.table("workers").select("*").execute()
        rows = response.data or []
        return [dict(row) for row in rows]
    except Exception:  # pragma: no cover - defensive error path
        return MOCK_WORKERS


@router.post("")
async def create_worker(request: WorkerCreateRequest) -> dict[str, Any]:
    """Create a new worker."""

    # Import here to allow test monkeypatching
    from app import main as main_module

    client = getattr(main_module, "supabase_client", None)
    if not client:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Supabase client unavailable")

    try:
        payload = {
            "name": request.name,
            "role": request.role or "assistant",
            "status": request.status or "active",
        }
        response = client.table("workers").insert(payload).execute()
        record = response.data[0] if response.data else None
        return {"success": True, "worker": record}
    except Exception as exc:  # pragma: no cover - defensive error path
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/{worker_id}/status")
async def get_worker_status(worker_id: str) -> dict[str, Any]:
    """Return the runtime state for a worker."""

    state = worker_runtime.get_worker_state(worker_id)
    return state


@router.post("/{worker_id}/run")
async def run_worker(worker_id: str) -> dict[str, Any]:
    """Execute all pending missions for a worker."""

    result = orchestrator.run_worker(worker_id)
    if not result.get("success"):
        error = result.get("error") or "Worker execution failed"
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error))
    return result
