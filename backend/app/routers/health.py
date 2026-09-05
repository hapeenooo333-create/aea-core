from fastapi import APIRouter

from app.database import is_supabase_configured, supabase_client
from app.services.agent_orchestrator import AgentOrchestrator

router = APIRouter()
orchestrator = AgentOrchestrator()


@router.get("/health")
def health_check() -> dict:
    payload = dict(orchestrator.health_check())
    payload.setdefault("status", "healthy")
    payload.setdefault("service", "aea-core-backend")
    payload["service"] = "aea-core-backend"
    payload["supabase_configured"] = bool(is_supabase_configured())
    payload["supabase_connected"] = bool(supabase_client)
    return payload
