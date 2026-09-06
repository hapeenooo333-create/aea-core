"""Connector API routes for Sprint 7.2-B.

Provides REST endpoints for platform connector operations, onboarding workflows,
and human intervention checkpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.dependencies import get_current_user_id
from app.services.connectors.pinterest_connector import PinterestConnector
from app.services.connectors.registry import ConnectorRegistry
from app.services.human_intervention import HumanInterventionManager
from app.services.worker_runtime import WorkerRuntime

router = APIRouter(
    prefix="/connectors",
    tags=["connectors"],
    dependencies=[Depends(get_current_user_id)],
)

# Initialize services
_connector_registry: ConnectorRegistry | None = None
_human_intervention_manager: HumanInterventionManager | None = None


def get_connector_registry() -> ConnectorRegistry:
    """Get or initialize the connector registry."""
    global _connector_registry
    if _connector_registry is None:
        _connector_registry = ConnectorRegistry()
        # Register Pinterest connector
        pinterest_connector = PinterestConnector()
        _connector_registry.register(pinterest_connector)
    return _connector_registry


def get_worker_runtime(current_user_id: str = Depends(get_current_user_id)) -> WorkerRuntime:
    """Get or initialize the worker runtime scoped to the current user."""
    registry = get_connector_registry()
    return WorkerRuntime(connector_registry=registry, owner_id=current_user_id)


def get_human_intervention_manager() -> HumanInterventionManager:
    """Get or initialize the human intervention manager."""
    global _human_intervention_manager
    if _human_intervention_manager is None:
        _human_intervention_manager = HumanInterventionManager()
    return _human_intervention_manager


# Pydantic models
class OnboardingStartRequest(BaseModel):
    """Request to start platform onboarding."""

    platform: str
    worker_id: str

    model_config = ConfigDict(extra="allow")


class OnboardingResumeRequest(BaseModel):
    """Request to resume platform onboarding."""

    workflow_id: str
    checkpoint_id: str | None = None
    human_input: dict[str, Any] = {}

    model_config = ConfigDict(extra="allow")


class CheckpointCompleteRequest(BaseModel):
    """Request to mark a checkpoint as completed."""

    human_input: dict[str, Any] = {}

    model_config = ConfigDict(extra="allow")


# Routes
@router.get("")
async def list_connectors() -> dict[str, Any]:
    """List all supported platform connectors."""
    registry = get_connector_registry()
    platforms = registry.list_platforms()
    capabilities = registry.list_capabilities()
    return {
        "success": True,
        "platforms": platforms,
        "capabilities": capabilities,
    }


@router.get("/{platform}")
async def get_connector_info(platform: str) -> dict[str, Any]:
    """Get information about a specific platform connector."""
    registry = get_connector_registry()
    if not registry.has_connector(platform):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No connector found for platform '{platform}'",
        )

    connector = registry.get(platform)
    capabilities = registry.get_capabilities_dict(platform)
    health = connector.health_check()

    return {
        "success": True,
        "platform": platform,
        "capabilities": capabilities,
        "health": health,
    }


@router.get("/{platform}/health")
async def connector_health(platform: str) -> dict[str, Any]:
    """Check the health of a platform connector."""
    registry = get_connector_registry()
    connector = registry.get(platform)

    if not connector:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No connector found for platform '{platform}'",
        )

    return connector.health_check()


@router.post("/onboarding/start")
async def start_onboarding(request: OnboardingStartRequest) -> dict[str, Any]:
    """Start a platform onboarding workflow."""
    platform = request.platform
    worker_id = request.worker_id

    registry = get_connector_registry()
    if not registry.has_connector(platform):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No connector found for platform '{platform}'",
        )

    connector = registry.get(platform)
    result = connector.start_onboarding(worker_id)

    return {
        "success": True,
        "workflow": result,
    }


@router.get("/onboarding/{workflow_id}")
async def get_onboarding_status(workflow_id: str) -> dict[str, Any]:
    """Get the status of an onboarding workflow."""
    # TODO: Retrieve workflow status from database or connector state
    return {
        "success": False,
        "error": "Workflow status retrieval not yet fully implemented",
        "workflow_id": workflow_id,
    }


@router.post("/onboarding/{workflow_id}/resume")
async def resume_onboarding(workflow_id: str, request: OnboardingResumeRequest) -> dict[str, Any]:
    """Resume an onboarding workflow after human intervention."""
    # Extract platform from workflow metadata if possible
    # For MVP, this would be stored in database
    return {
        "success": False,
        "error": "Workflow resume not yet fully implemented",
        "workflow_id": workflow_id,
    }


@router.get("/checkpoints/pending")
async def list_pending_checkpoints(
    mission_id: str | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """List pending human intervention checkpoints."""
    manager = get_human_intervention_manager()
    checkpoints = manager.list_pending_checkpoints(
        mission_id=mission_id,
        platform=platform,
    )
    return {
        "success": True,
        "checkpoints": checkpoints,
        "count": len(checkpoints),
    }


@router.get("/checkpoints/{checkpoint_id}")
async def get_checkpoint(checkpoint_id: str) -> dict[str, Any]:
    """Get a specific human intervention checkpoint."""
    manager = get_human_intervention_manager()
    checkpoint = manager.get_checkpoint(checkpoint_id)

    if not checkpoint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Checkpoint '{checkpoint_id}' not found",
        )

    return {
        "success": True,
        "checkpoint": checkpoint,
    }


@router.post("/checkpoints/{checkpoint_id}/complete")
async def complete_checkpoint(checkpoint_id: str, request: CheckpointCompleteRequest) -> dict[str, Any]:
    """Mark a checkpoint as completed by the human."""
    manager = get_human_intervention_manager()
    result = manager.complete_checkpoint(
        checkpoint_id,
        human_input=request.human_input,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "Failed to complete checkpoint"),
        )

    return {
        "success": True,
        "checkpoint": result.get("checkpoint"),
    }
