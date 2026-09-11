"""Approval API routes for Sprint 7.2-A + P1-1 resume pipeline."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from app.dependencies import get_current_user_id, get_user_scoped_client, verify_ownership
from app.services.approval_gateway import ApprovalGateway
from app.services.approval_resume_service import ApprovalResumeService
from app.services.connectors.pinterest_connector import PinterestConnector
from app.services.connectors.registry import ConnectorRegistry
from app.services.human_intervention import HumanInterventionManager
from app.services.mission_execution_service import MissionExecutionService
from app.services.stores.onboarding_workflow_store import OnboardingWorkflowStore

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _build_resume_service(current_user_id: str | None = None) -> ApprovalResumeService:
    """Construct an ``ApprovalResumeService`` with the canonical registry."""

    registry = ConnectorRegistry()
    registry.register(PinterestConnector(workflow_store=OnboardingWorkflowStore(durable_required=True)))
    return ApprovalResumeService(
        approval_gateway=ApprovalGateway(),
        connector_registry=registry,
        human_intervention_manager=HumanInterventionManager(),
    )


resume_service = _build_resume_service()


class ApprovalApproveRequest(BaseModel):
    """Request payload for approving an approval request."""

    approved_by: str | None = None

    model_config = ConfigDict(extra="allow")


class ApprovalRejectRequest(BaseModel):
    """Request payload for rejecting an approval request."""

    reason: str | None = None
    rejected_by: str | None = None

    model_config = ConfigDict(extra="allow")


class ApprovalListFilters(BaseModel):
    """Query parameters for filtering approvals."""

    mission_id: str | None = None
    status: str | None = None
    limit: int = 100

    model_config = ConfigDict(extra="allow")


def _get_approval_gateway(client: Any | None = None) -> ApprovalGateway:
    """Get an ApprovalGateway instance with optional scoped client."""
    return ApprovalGateway(client=client)


def _get_resume_service(current_user_id: str, client: Any | None = None) -> ApprovalResumeService:
    """Get an ApprovalResumeService scoped to the current user."""
    registry = ConnectorRegistry()
    registry.register(
        PinterestConnector(
            workflow_store=OnboardingWorkflowStore(
                client=client,
                durable_required=True,
            ),
        ),
    )
    return ApprovalResumeService(
        approval_gateway=ApprovalGateway(client=client),
        connector_registry=registry,
        human_intervention_manager=HumanInterventionManager(),
    )


@router.get("/{approval_id}")
async def get_approval(
    approval_id: str,
    current_user_id: str = Depends(get_current_user_id),
    client: Any = Depends(get_user_scoped_client),
) -> dict[str, Any]:
    """Retrieve a specific approval request owned by the current user."""

    gateway = _get_approval_gateway(client)
    approval = gateway.get_request(approval_id, client=client)
    if approval is None or approval.get("owner_id") != current_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")
    return {"success": True, "approval": approval}


@router.get("")
async def list_approvals(
    current_user_id: str = Depends(get_current_user_id),
    client: Any = Depends(get_user_scoped_client),
    mission_id: str | None = None,
    status_filter: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List approval requests owned by the current user with optional filtering."""

    gateway = _get_approval_gateway(client)
    approvals = gateway.list_requests(
        mission_id=mission_id,
        status=status_filter,
        limit=limit,
        client=client,
    )
    # Filter to only current user's approvals for defense in depth
    user_approvals = [a for a in approvals if a.get("owner_id") == current_user_id]
    return {"success": True, "approvals": user_approvals, "count": len(user_approvals)}


@router.post("/{approval_id}/approve", status_code=status.HTTP_200_OK)
async def approve_approval(
    approval_id: str,
    request: ApprovalApproveRequest,
    current_user_id: str = Depends(get_current_user_id),
    client: Any = Depends(get_user_scoped_client),
) -> dict[str, Any]:
    """Approve a pending approval request and trigger resume.

    The authenticated user must own the approval request.
    The ``approved_by`` field is derived from current_user_id,
    never from the request body.
    """

    gateway = _get_approval_gateway(client)
    approval = gateway.get_request(approval_id, client=client)
    if approval is None or approval.get("owner_id") != current_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

    result = gateway.approve_request(approval_id, approved_by=current_user_id)

    if not result.get("success"):
        error = result.get("error", "Failed to approve request")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))

    approval = result.get("request")
    resume_result = _get_resume_service(current_user_id, client).resume(
        approval_id,
        current_user_id=current_user_id,
    )
    return {
        "success": True,
        "approval": approval,
        "resume": resume_result,
    }


@router.post("/{approval_id}/reject", status_code=status.HTTP_200_OK)
async def reject_approval(
    approval_id: str,
    request: ApprovalRejectRequest,
    current_user_id: str = Depends(get_current_user_id),
    client: Any = Depends(get_user_scoped_client),
) -> dict[str, Any]:
    """Reject a pending approval request.

    The authenticated user must own the approval request.
    The ``rejected_by`` field is derived from current_user_id,
    never from the request body.
    """

    gateway = _get_approval_gateway(client)
    approval = gateway.get_request(approval_id, client=client)
    if approval is None or approval.get("owner_id") != current_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

    result = gateway.reject_request(
        approval_id,
        reason=request.reason or "",
        rejected_by=current_user_id,
    )

    if not result.get("success"):
        error = result.get("error", "Failed to reject request")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))

    rejected_request = result.get("request") or approval
    execution_id = (rejected_request.get("payload") or {}).get("execution_id")
    if execution_id:
        terminal = MissionExecutionService(client=client, durable_required=True).mark_failed(
            execution_id,
            current_user_id,
            error="Approval rejected",
            result={"decision": "REJECTED", "approval_request_id": approval_id},
        )
        if not terminal.get("success"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=terminal.get("error", "Failed to persist rejected execution"),
            )

    return {"success": True, "approval": result.get("request")}