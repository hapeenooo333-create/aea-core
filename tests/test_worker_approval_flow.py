"""Tests for worker approval flow integration."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.worker_runtime import WorkerRuntime


def test_execute_action_with_approval_safe_action():
    """Test that safe actions execute immediately without approval."""
    runtime = WorkerRuntime()

    result = runtime.execute_action_with_approval(
        mission_id="mission-123",
        action_type="research",
        payload={"query": "test query"},
    )

    # Safe action should execute immediately
    assert result["success"] is True
    assert "pending_approval" not in result or result.get("pending_approval") is not True


def test_execute_action_with_approval_sensitive_action():
    """Test that sensitive actions require approval."""
    runtime = WorkerRuntime()

    result = runtime.execute_action_with_approval(
        mission_id="mission-123",
        action_type="publish_content",
        payload={"content": "test content"},
    )

    # Sensitive action should return pending approval
    assert result["pending_approval"] is True
    assert result["approval_request_id"] is not None
    assert result["action_type"] == "publish_content"
    assert result["risk_level"] == "sensitive"


def test_execute_action_with_approval_create_account():
    """Test that create_account action requires approval."""
    runtime = WorkerRuntime()

    result = runtime.execute_action_with_approval(
        mission_id="mission-456",
        action_type="create_account",
        payload={"account_type": "email"},
    )

    assert result["pending_approval"] is True
    assert result["action_type"] == "create_account"
    assert result["risk_level"] == "sensitive"


def test_continue_with_approval_when_not_approved():
    """Test that continuing without approval fails."""
    runtime = WorkerRuntime()

    # Request action (which requires approval)
    request_result = runtime.execute_action_with_approval(
        mission_id="mission-123",
        action_type="publish_content",
        payload={"content": "test"},
    )
    approval_request_id = request_result["approval_request_id"]

    # Try to continue without approval
    continue_result = runtime.continue_with_approval(
        mission_id="mission-123",
        approval_request_id=approval_request_id,
        action_type="publish_content",
        payload={"content": "test"},
    )

    assert continue_result["success"] is False
    assert "not granted" in continue_result["error"].lower()


def test_continue_with_approval_when_approved():
    """Test that continuing with approval succeeds."""
    runtime = WorkerRuntime()

    # Request action (which requires approval)
    request_result = runtime.execute_action_with_approval(
        mission_id="mission-123",
        action_type="publish_content",
        payload={"content": "test"},
    )
    approval_request_id = request_result["approval_request_id"]

    # Approve the request
    runtime._approval_gateway.approve_request(approval_request_id)

    # Now continue with approval
    continue_result = runtime.continue_with_approval(
        mission_id="mission-123",
        approval_request_id=approval_request_id,
        action_type="publish_content",
        payload={"content": "test"},
    )

    # Result depends on action execution
    # The publish_content action is not implemented, so may fail
    # But it should not be due to lack of approval
    assert "not granted" not in str(continue_result).lower()


def test_sensitive_action_pause_and_continue():
    """Test complete sensitive action pause and continue workflow."""
    runtime = WorkerRuntime()

    # Step 1: Request action
    result = runtime.execute_action_with_approval(
        mission_id="mission-789",
        action_type="connect_platform",
        payload={"platform": "twitter"},
    )

    assert result["pending_approval"] is True
    approval_id = result["approval_request_id"]

    # Step 2: Verify request pending
    request = runtime._approval_gateway.get_request(approval_id)
    assert request["status"] == "pending"

    # Step 3: Approve the request
    approve_result = runtime._approval_gateway.approve_request(approval_id)
    assert approve_result["success"] is True

    # Step 4: Check request is now approved
    request = runtime._approval_gateway.get_request(approval_id)
    assert request["status"] == "approved"

    # Step 5: Continue execution
    continue_result = runtime.continue_with_approval(
        mission_id="mission-789",
        approval_request_id=approval_id,
        action_type="connect_platform",
        payload={"platform": "twitter"},
    )

    # Should not complain about approval
    assert "not granted" not in str(continue_result).lower()


def test_action_envelope_creation():
    """Test that action envelopes are properly created."""
    runtime = WorkerRuntime()

    # Request safe action
    safe_envelope = runtime._action_engine.create_action_envelope(
        "research",
        {"query": "test"},
    )
    assert safe_envelope["requires_approval"] is False

    # Request sensitive action
    sensitive_envelope = runtime._action_engine.create_action_envelope(
        "publish_content",
        {"content": "test"},
    )
    assert sensitive_envelope["requires_approval"] is True


def test_multiple_approval_requests():
    """Test managing multiple approval requests in runtime."""
    runtime = WorkerRuntime()

    # Request multiple sensitive actions
    results = []
    for i in range(3):
        result = runtime.execute_action_with_approval(
            mission_id=f"mission-{i}",
            action_type="publish_content",
            payload={"content": f"content-{i}"},
        )
        results.append(result)

    # All should be pending approval
    approval_ids = [r["approval_request_id"] for r in results]
    for approval_id in approval_ids:
        assert runtime._approval_gateway.is_approved(approval_id) is False

    # Approve first two
    runtime._approval_gateway.approve_request(approval_ids[0])
    runtime._approval_gateway.approve_request(approval_ids[1])

    # Verify approval state
    assert runtime._approval_gateway.is_approved(approval_ids[0]) is True
    assert runtime._approval_gateway.is_approved(approval_ids[1]) is True
    assert runtime._approval_gateway.is_approved(approval_ids[2]) is False


def test_safe_actions_dont_create_approval_requests():
    """Test that safe actions don't create approval requests."""
    runtime = WorkerRuntime()

    result = runtime.execute_action_with_approval(
        mission_id="mission-123",
        action_type="analysis",
        payload={"query": "test analysis"},
    )

    # Should not have approval request
    assert "approval_request_id" not in result or result.get("approval_request_id") is None
    assert result.get("pending_approval") is not True
