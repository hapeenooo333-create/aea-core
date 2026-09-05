"""Approval API routes for Sprint 7.2-A + P1-1 resume pipeline."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.services.approval_gateway import ApprovalGateway
from app.services.approval_resume_service import ApprovalResumeService
from app.services.connectors.pinterest_connector import PinterestConnector
from app.services.connectors.registry import ConnectorRegistry
from app.services.human_intervention import HumanInterventionManager

router = APIRouter(prefix="/approvals", tags=["approvals"])
approval_gateway = ApprovalGateway()


def _build_resume_service() -> ApprovalResumeService:
    """Construct an ``ApprovalResumeService`` with the canonical registry."""
    registry = ConnectorRegistry()
    registry.register(PinterestConnector())
    return ApprovalResumeService(
        approval_gateway=approval_gateway,
        connector_registry=registry,
        human_intervention_manager=HumanInterventionManager(),
    )


resume_service: ApprovalResumeService = _build_resume_service()


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


@router.get("/{approval_id}")
async def get_approval(approval_id: str) -> dict[str, Any]:
    """Retrieve a specific approval request."""

    approval = approval_gateway.get_request(approval_id)
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")
    return {"success": True, "approval": approval}


@router.get("")
async def list_approvals(mission_id: str | None = None, status_filter: str | None = None, limit: int = 100) -> dict[str, Any]:
    """List approval requests with optional filtering.

    Query Parameters:
        mission_id: Optional filter by mission ID
        status_filter: Optional filter by status (pending, approved, rejected, expired)
        limit: Maximum number of results (default: 100)
    """

    approvals = approval_gateway.list_requests(
        mission_id=mission_id,
        status=status_filter,
        limit=limit,
    )
    return {"success": True, "approvals": approvals, "count": len(approvals)}


@router.post("/{approval_id}/approve", status_code=status.HTTP_200_OK)
async def approve_approval(approval_id: str, request: ApprovalApproveRequest) -> dict[str, Any]:
    """Approve a pending approval request and trigger resume.

    On success the response includes the persisted approval record plus a
    ``resume`` field describing the outcome of the resume pipeline.
    """

    result = approval_gateway.approve_request(approval_id, approved_by=request.approved_by)

    if not result.get("success"):
        error = result.get("error", "Failed to approve request")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))

    approval = result.get("request")
    resume_result = resume_service.resume(approval_id)
    return {
        "success": True,
        "approval": approval,
        "resume": resume_result,
    }


@router.post("/{approval_id}/reject", status_code=status.HTTP_200_OK)
async def reject_approval(approval_id: str, request: ApprovalRejectRequest) -> dict[str, Any]:
    """Reject a pending approval request.

    Rejection does not invoke the resume pipeline.
    """

    result = approval_gateway.reject_request(
        approval_id,
        reason=request.reason or "",
        rejected_by=request.rejected_by,
    )

    if not result.get("success"):
        error = result.get("error", "Failed to reject request")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))

    return {"success": True, "approval": result.get("request")}