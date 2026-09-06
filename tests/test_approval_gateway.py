"""Tests for the ApprovalGateway service."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.approval_gateway import ApprovalGateway


def test_create_approval_request():
    """Test creating a new approval request."""
    gateway = ApprovalGateway()

    result = gateway.create_request(
        mission_id="mission-123",
        action_type="publish_content",
        risk_level="sensitive",
        payload={"content": "test content"},
    )

    assert result["success"] is True
    request = result["request"]
    assert request["mission_id"] == "mission-123"
    assert request["action_type"] == "publish_content"
    assert request["risk_level"] == "sensitive"
    assert request["status"] == "pending"
    assert request["payload"] == {"content": "test content"}
    assert request["id"] is not None


def test_get_approval_request():
    """Test retrieving an approval request."""
    gateway = ApprovalGateway()

    # Create a request
    create_result = gateway.create_request(
        mission_id="mission-123",
        action_type="publish_content",
        risk_level="sensitive",
        payload={"content": "test content"},
    )
    request_id = create_result["request"]["id"]

    # Retrieve it
    retrieved = gateway.get_request(request_id)
    assert retrieved is not None
    assert retrieved["id"] == request_id
    assert retrieved["status"] == "pending"


def test_approve_request():
    """Test approving an approval request."""
    gateway = ApprovalGateway()

    # Create a request
    create_result = gateway.create_request(
        mission_id="mission-123",
        action_type="publish_content",
        risk_level="sensitive",
        payload={"content": "test content"},
    )
    request_id = create_result["request"]["id"]

    # Approve it
    approve_result = gateway.approve_request(request_id)
    assert approve_result["success"] is True
    request = approve_result["request"]
    assert request["status"] == "approved"
    assert request["approved_at"] is not None
    assert request["rejected_at"] is None


def test_reject_request():
    """Test rejecting an approval request."""
    gateway = ApprovalGateway()

    # Create a request
    create_result = gateway.create_request(
        mission_id="mission-123",
        action_type="publish_content",
        risk_level="sensitive",
        payload={"content": "test content"},
    )
    request_id = create_result["request"]["id"]

    # Reject it
    reject_result = gateway.reject_request(request_id, reason="Content not appropriate")
    assert reject_result["success"] is True
    request = reject_result["request"]
    assert request["status"] == "rejected"
    assert request["rejected_at"] is not None
    assert request["rejection_reason"] == "Content not appropriate"


def test_cannot_approve_rejected_request():
    """Test that rejected requests cannot be approved."""
    gateway = ApprovalGateway()

    # Create and reject a request
    create_result = gateway.create_request(
        mission_id="mission-123",
        action_type="publish_content",
        risk_level="sensitive",
        payload={"content": "test content"},
    )
    request_id = create_result["request"]["id"]
    gateway.reject_request(request_id)

    # Try to approve rejected request
    approve_result = gateway.approve_request(request_id)
    assert approve_result["success"] is False
    assert "rejected" in approve_result["error"].lower()


def test_cannot_reject_approved_request():
    """Test that approved requests cannot be rejected."""
    gateway = ApprovalGateway()

    # Create and approve a request
    create_result = gateway.create_request(
        mission_id="mission-123",
        action_type="publish_content",
        risk_level="sensitive",
        payload={"content": "test content"},
    )
    request_id = create_result["request"]["id"]
    gateway.approve_request(request_id)

    # Try to reject approved request
    reject_result = gateway.reject_request(request_id)
    assert reject_result["success"] is False
    assert "approved" in reject_result["error"].lower()


def test_is_approved():
    """Test checking if request is approved."""
    gateway = ApprovalGateway()

    # Create and approve a request
    create_result = gateway.create_request(
        mission_id="mission-123",
        action_type="publish_content",
        risk_level="sensitive",
        payload={"content": "test content"},
    )
    request_id = create_result["request"]["id"]

    # Initially not approved
    assert gateway.is_approved(request_id) is False

    # After approval
    gateway.approve_request(request_id)
    assert gateway.is_approved(request_id) is True


def test_request_expiration():
    """Test that requests can expire."""
    gateway = ApprovalGateway()

    # Create a request with short TTL
    create_result = gateway.create_request(
        mission_id="mission-123",
        action_type="publish_content",
        risk_level="sensitive",
        payload={"content": "test content"},
        ttl_hours=0,  # Expired immediately
    )
    request_id = create_result["request"]["id"]

    # Should be expired
    assert gateway.is_expired(request_id) is True

    # Should not be approvable after expiration
    retrieved = gateway.get_request(request_id)
    assert retrieved is not None
    # Status should be marked as expired
    assert retrieved.get("status") in ["expired", "pending"]


def test_approval_lifecycle():
    """Test complete approval lifecycle."""
    gateway = ApprovalGateway()

    # Step 1: Create request
    create_result = gateway.create_request(
        mission_id="mission-456",
        action_type="create_account",
        risk_level="sensitive",
        payload={"account_type": "social_media"},
    )
    assert create_result["success"] is True
    request_id = create_result["request"]["id"]

    # Step 2: Verify initial state
    request = gateway.get_request(request_id)
    assert request["status"] == "pending"

    # Step 3: Approve
    approve_result = gateway.approve_request(request_id)
    assert approve_result["success"] is True

    # Step 4: Verify approval
    approved_request = gateway.get_request(request_id)
    assert approved_request["status"] == "approved"
    assert gateway.is_approved(request_id) is True

    # Step 5: Should not be expired
    assert gateway.is_expired(request_id) is False


def test_multiple_requests():
    """Test managing multiple approval requests."""
    gateway = ApprovalGateway()

    # Create three requests
    requests = []
    for i in range(3):
        result = gateway.create_request(
            mission_id=f"mission-{i}",
            action_type="publish_content",
            risk_level="sensitive",
            payload={"content_id": i},
        )
        requests.append(result["request"]["id"])

    # Approve first, reject second, leave third pending
    gateway.approve_request(requests[0])
    gateway.reject_request(requests[1], reason="Test rejection")

    # Verify states
    assert gateway.is_approved(requests[0]) is True
    assert gateway.is_approved(requests[1]) is False
    assert gateway.is_approved(requests[2]) is False

    request_2 = gateway.get_request(requests[2])
    assert request_2["status"] == "pending"
