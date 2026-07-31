import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from app.config import settings
from app.database import is_supabase_configured, supabase_client
from app.routers.atlas import router as atlas_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Initial backend for AEA Core",
)

app.include_router(atlas_router)

MOCK_WORKERS = [
    {"id": 1, "name": "Atlas", "role": "CEO", "status": "active"},
    {"id": 2, "name": "Pine", "role": "Pinterest Worker", "status": "active"},
]


class WorkerCreate(BaseModel):
    name: str
    role: str
    status: str


class WorkerResponse(BaseModel):
    id: int | str | None = None
    name: str | None = None
    role: str | None = None
    status: str | None = None

    model_config = ConfigDict(extra="allow")


class MissionResponse(BaseModel):
    id: int | str | None = None
    name: str | None = None
    status: str | None = None
    description: str | None = None

    model_config = ConfigDict(extra="allow")


@app.get("/")
async def read_root() -> dict[str, str]:
    return {"message": "AEA Core API is running"}


@app.get("/health")
async def health_check() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "aea-core-backend",
        "supabase_configured": is_supabase_configured(),
        "supabase_connected": bool(supabase_client),
    }


@app.get("/workers", response_model=list[WorkerResponse])
async def get_workers() -> list[WorkerResponse]:
    if not supabase_client:
        return [WorkerResponse(**row) for row in MOCK_WORKERS]

    try:
        response = supabase_client.table("workers").select("*").execute()
        rows = response.data or []
        if not rows:
            return [WorkerResponse(**row) for row in MOCK_WORKERS]
        return [WorkerResponse(**row) for row in rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch workers") from exc


def _format_supabase_error(exc: Exception) -> str:
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


@app.post("/workers", response_model=WorkerResponse)
async def create_worker(worker: WorkerCreate) -> WorkerResponse:
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client unavailable")

    try:
        payload: dict[str, Any] = worker.dict() if hasattr(worker, "dict") else worker.model_dump()
        response = supabase_client.table("workers").insert(payload).execute()
        rows = response.data or []
        if not rows:
            raise HTTPException(status_code=500, detail="Worker creation returned no data")
        return WorkerResponse(**rows[0])
    except HTTPException:
        raise
    except Exception as exc:
        error_message = _format_supabase_error(exc)
        logger.exception("Failed to create worker in Supabase: %s", error_message)
        raise HTTPException(status_code=500, detail=f"Failed to create worker: {error_message}") from exc


@app.get("/missions", response_model=list[MissionResponse])
async def get_missions() -> list[MissionResponse]:
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client unavailable")

    try:
        response = supabase_client.table("missions").select("*").execute()
        rows = response.data or []
        return [MissionResponse(**row) for row in rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to fetch missions") from exc
