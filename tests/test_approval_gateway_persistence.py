"""Tests for approval gateway persistence layer (Sprint 7.2-A)."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from app.services.approval_gateway import ApprovalGateway, ApprovalRequest


class TestApprovalRequestClass:
    """Test the ApprovalRequest class."""

    def test_approval_request_initialization(self) -> None:
        """Test creating an approval request."""
        request = ApprovalRequest(
            request_id="test-123",
            mission_id="mission-1",
            action_type="send_message",
            risk_level="sensitive",
            payload={"message": "hello"},
        )
        assert request.request_id == "test-123"
        assert request.mission_id == "mission-1"
        assert request.status == "pending"
        assert request.approved_at is None
        assert request.rejected_at is None

    def test_approval_request_to_dict(self) -> None:
        """Test converting request to dictionary."""
        request = ApprovalRequest(
            request_id="test-123",
            mission_id="mission-1",
            action_type="send_message",
            risk_level="sensitive",
            payload={"message": "hello"},
        )
        result = request.to_dict()
        assert result["id"] == "test-123"
        assert result["mission_id"] == "mission-1"
        assert result["action_type"] == "send_message"
        assert result["status"] == "pending"


class TestApprovalGatewayPersistence:
    """Test approval gateway persistence features."""

    def test_create_request_with_database(self) -> None:
        """Test creating request with database available."""
        gateway = ApprovalGateway()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [{"id": "test-123"}]
        mock_client.table().insert().execute.return_value = mock_response
        gateway._client = mock_client

        result = gateway.create_request(
            mission_id="mission-1",
            action_type="send_message",
            risk_level="sensitive",
            payload={"message": "hello"},
        )

        assert result["success"] is True
        assert result["request"]["status"] == "pending"
        # Verify database was called
        mock_client.table.assert_called()

    def test_create_request_fallback_to_memory(self) -> None:
        """P1-2: real DB errors are surfaced; only ``db_unavailable`` falls
        back to the in-memory dict. A generic ``Exception`` is a real DB
        error and the gateway must NOT silently swap to stale memory."""
        gateway = ApprovalGateway()
        mock_client = MagicMock()
        mock_client.table().insert().execute.side_effect = Exception("DB error")
        gateway._client = mock_client

        result = gateway.create_request(
            mission_id="mission-1",
            action_type="send_message",
            risk_level="sensitive",
            payload={"message": "hello"},
        )

        # The error is propagated, not swallowed.
        assert result["success"] is False
        assert "db_error" in result["error"]
        # No silent write to memory.
        assert gateway._memory_store == {}

    def test_create_request_no_database(self) -> None:
        """Test creating request when no database is available."""
        gateway = ApprovalGateway()
        gateway._client = None

        result = gateway.create_request(
            mission_id="mission-1",
            action_type="send_message",
            risk_level="sensitive",
            payload={"message": "hello"},
        )

        assert result["success"] is True
        request_id = result["request"]["id"]
        assert request_id in gateway._memory_store

    def test_get_request_from_database(self) -> None:
        """Test retrieving request from database."""
        gateway = ApprovalGateway()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [
            {
                "id": "test-123",
                "mission_id": "mission-1",
                "action_type": "send_message",
                "risk_level": "sensitive",
                "status": "pending",
                "requested_at": "2024-01-01T00:00:00+00:00",
                "expires_at": "2024-01-02T00:00:00+00:00",
                "metadata": {"message": "hello"},
            }
        ]
        mock_client.table().select().eq().limit().execute.return_value = mock_response
        gateway._client = mock_client

        result = gateway.get_request("test-123")
        assert result is not None
        assert result["id"] == "test-123"
        assert result["mission_id"] == "mission-1"

    def test_get_request_from_memory(self) -> None:
        """Test retrieving request from memory store."""
        gateway = ApprovalGateway()
        gateway._client = None

        # First create a request
        create_result = gateway.create_request(
            mission_id="mission-1",
            action_type="send_message",
            risk_level="sensitive",
            payload={"message": "hello"},
        )

        request_id = create_result["request"]["id"]
        result = gateway.get_request(request_id)
        assert result is not None
        assert result["id"] == request_id

    def test_list_requests_with_filters(self) -> None:
        """Test listing requests with mission_id and status filters."""
        gateway = ApprovalGateway()
        gateway._client = None

        # Create multiple requests
        gateway.create_request("mission-1", "send_message", "sensitive", {})
        gateway.create_request("mission-2", "send_message", "sensitive", {})

        # Get without filters
        all_requests = gateway.list_requests()
        assert len(all_requests) >= 2

        # Filter by mission
        mission1_requests = gateway.list_requests(mission_id="mission-1")
        assert all(r["mission_id"] == "mission-1" for r in mission1_requests)

    def test_approve_request_updates_database(self) -> None:
        """Test approving a request updates database via atomic compare-and-set."""
        gateway = ApprovalGateway()
        mock_client = MagicMock()
        # Create path: insert returns a row containing the new id.
        mock_client.table().insert().execute.return_value = MagicMock(data=[{"id": "test-123"}])
        # Approve path: the gateway performs a ``.update().eq(id).eq(status).execute()``
        # compare-and-set. The mock returns the post-update row.
        updated_row = {
            "id": "test-123",
            "mission_id": "mission-1",
            "action_type": "send_message",
            "risk_level": "sensitive",
            "status": "approved",
            "requested_at": "2024-01-01T00:00:00+00:00",
            "expires_at": "2024-01-02T00:00:00+00:00",
            "approved_at": "2024-01-01T01:00:00+00:00",
            "approved_by": "user-1",
            "metadata": {},
        }
        mock_client.table().update().eq().eq().execute.return_value = MagicMock(
            data=[updated_row]
        )
        # Probe path: the compare-and-set may re-read the row when the
        # update matches zero rows. The mock returns a pending row so the
        # probe path is exercised but does not affect the happy path.
        mock_client.table().select().eq().limit().execute.return_value = MagicMock(
            data=[dict(updated_row, status="pending")]
        )
        gateway._client = mock_client

        # Create request
        create_result = gateway.create_request(
            mission_id="mission-1",
            action_type="send_message",
            risk_level="sensitive",
            payload={},
        )
        request_id = create_result["request"]["id"]

        # Approve request
        approve_result = gateway.approve_request(request_id, approved_by="user-1")
        assert approve_result["success"] is True
        assert approve_result["request"]["status"] == "approved"
        assert approve_result["request"]["approved_by"] == "user-1"

    def test_reject_request_with_reason(self) -> None:
        """Test rejecting a request with reason."""
        gateway = ApprovalGateway()
        gateway._client = None

        # Create request
        create_result = gateway.create_request(
            mission_id="mission-1",
            action_type="send_message",
            risk_level="sensitive",
            payload={},
        )
        request_id = create_result["request"]["id"]

        # Reject with reason
        reject_result = gateway.reject_request(request_id, reason="Too risky", rejected_by="user-2")
        assert reject_result["success"] is True
        assert reject_result["request"]["status"] == "rejected"
        assert reject_result["request"]["rejection_reason"] == "Too risky"
        assert reject_result["request"]["rejected_by"] == "user-2"

    def test_is_approved_check(self) -> None:
        """Test checking if request is approved."""
        gateway = ApprovalGateway()
        gateway._client = None

        # Create and approve request
        create_result = gateway.create_request(
            mission_id="mission-1",
            action_type="send_message",
            risk_level="sensitive",
            payload={},
        )
        request_id = create_result["request"]["id"]

        # Initially not approved
        assert gateway.is_approved(request_id) is False

        # After approval
        gateway.approve_request(request_id)
        assert gateway.is_approved(request_id) is True

    def test_is_expired_check(self) -> None:
        """Test checking if request is expired."""
        gateway = ApprovalGateway()
        gateway._client = None

        # Create request with short TTL
        create_result = gateway.create_request(
            mission_id="mission-1",
            action_type="send_message",
            risk_level="sensitive",
            payload={},
            ttl_hours=0,  # Already expired
        )
        request_id = create_result["request"]["id"]

        # Should be expired
        assert gateway.is_expired(request_id) is True

    def test_normalize_request_from_database(self) -> None:
        """Test normalizing a database row."""
        gateway = ApprovalGateway()

        row = {
            "id": "test-123",
            "mission_id": "mission-1",
            "action_type": "send_message",
            "risk_level": "sensitive",
            "status": "pending",
            "requested_at": "2024-01-01T00:00:00+00:00",
            "expires_at": "2024-01-02T00:00:00+00:00",
            "metadata": {"message": "hello"},
            "approved_at": None,
            "rejected_at": None,
            "approved_by": None,
            "rejected_by": None,
            "reason": None,
        }

        normalized = gateway._normalize_request(row)
        assert normalized["id"] == "test-123"
        assert normalized["mission_id"] == "mission-1"
        assert normalized["payload"] == {"message": "hello"}

    def test_normalize_request_handles_both_timestamps(self) -> None:
        """Test that normalize handles both created_at and requested_at."""
        gateway = ApprovalGateway()

        # Test with requested_at
        row1 = {
            "id": "test-1",
            "mission_id": "mission-1",
            "action_type": "send_message",
            "risk_level": "sensitive",
            "status": "pending",
            "requested_at": "2024-01-01T00:00:00+00:00",
            "expires_at": "2024-01-02T00:00:00+00:00",
            "metadata": {},
        }
        result1 = gateway._normalize_request(row1)
        assert result1["created_at"] == "2024-01-01T00:00:00+00:00"

        # Test with created_at
        row2 = {
            "id": "test-2",
            "mission_id": "mission-1",
            "action_type": "send_message",
            "risk_level": "sensitive",
            "status": "pending",
            "created_at": "2024-01-01T01:00:00+00:00",
            "expires_at": "2024-01-02T00:00:00+00:00",
            "metadata": {},
        }
        result2 = gateway._normalize_request(row2)
        assert result2["created_at"] == "2024-01-01T01:00:00+00:00"


class TestApprovalGatewayIntegration:
    """Integration tests for approval gateway with fallback behavior."""

    def test_approve_workflow_with_memory_storage(self) -> None:
        """Test full approval workflow using memory storage."""
        gateway = ApprovalGateway()
        gateway._client = None

        # Create request
        create_result = gateway.create_request(
            mission_id="mission-1",
            action_type="create_account",
            risk_level="sensitive",
            payload={"account_type": "instagram"},
        )
        request_id = create_result["request"]["id"]

        # Verify pending
        request = gateway.get_request(request_id)
        assert request["status"] == "pending"

        # Approve
        approve_result = gateway.approve_request(request_id, approved_by="supervisor")
        assert approve_result["success"] is True

        # Verify approved
        request = gateway.get_request(request_id)
        assert request["status"] == "approved"
        assert request["approved_by"] == "supervisor"

    def test_reject_workflow_with_memory_storage(self) -> None:
        """Test full rejection workflow using memory storage."""
        gateway = ApprovalGateway()
        gateway._client = None

        # Create request
        create_result = gateway.create_request(
            mission_id="mission-2",
            action_type="send_message",
            risk_level="sensitive",
            payload={"recipient": "customer"},
        )
        request_id = create_result["request"]["id"]

        # Reject
        reject_result = gateway.reject_request(request_id, reason="Unauthorized", rejected_by="reviewer")
        assert reject_result["success"] is True

        # Verify rejected
        request = gateway.get_request(request_id)
        assert request["status"] == "rejected"
        assert request["rejection_reason"] == "Unauthorized"

    def test_cannot_approve_rejected_request(self) -> None:
        """Test that cannot approve already rejected request."""
        gateway = ApprovalGateway()
        gateway._client = None

        # Create and reject
        create_result = gateway.create_request(
            mission_id="mission-3",
            action_type="send_message",
            risk_level="sensitive",
            payload={},
        )
        request_id = create_result["request"]["id"]
        gateway.reject_request(request_id, reason="Bad request")

        # Try to approve
        approve_result = gateway.approve_request(request_id)
        assert approve_result["success"] is False
        assert "rejected" in approve_result["error"].lower()

    def test_cannot_reject_approved_request(self) -> None:
        """Test that cannot reject already approved request."""
        gateway = ApprovalGateway()
        gateway._client = None

        # Create and approve
        create_result = gateway.create_request(
            mission_id="mission-4",
            action_type="send_message",
            risk_level="sensitive",
            payload={},
        )
        request_id = create_result["request"]["id"]
        gateway.approve_request(request_id)

        # Try to reject
        reject_result = gateway.reject_request(request_id, reason="Changed mind")
        assert reject_result["success"] is False
        assert "approved" in reject_result["error"].lower()
