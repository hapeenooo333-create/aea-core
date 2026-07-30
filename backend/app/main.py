from fastapi import FastAPI

from app.config import settings
from app.database import is_supabase_configured, supabase_client

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Initial backend for AEA Core",
)

MOCK_WORKERS = [
    {"id": 1, "name": "Atlas", "role": "CEO", "status": "active"},
    {"id": 2, "name": "Pine", "role": "Pinterest Worker", "status": "active"},
]


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


@app.get("/workers", response_model=list[dict[str, object]])
async def get_workers() -> list[dict[str, object]]:
    if not supabase_client:
        return MOCK_WORKERS

    try:
        response = supabase_client.from_("workers").select("*").execute()
        rows = response.data or []
        return [dict(row) for row in rows]
    except Exception:
        return MOCK_WORKERS
