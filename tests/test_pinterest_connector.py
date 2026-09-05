"""Tests for Pinterest connector."""

import pytest

from app.services.connectors.pinterest_connector import PinterestConnector


def test_pinterest_platform_name():
    """Test Pinterest connector platform name."""
    connector = PinterestConnector()

    assert connector.platform == "pinterest"


def test_pinterest_capabilities():
    """Test Pinterest connector capabilities."""
    connector = PinterestConnector()
    caps = connector.capabilities

    assert caps.platform == "pinterest"
    assert caps.health_check
    assert caps.account_status
    assert caps.onboarding
    assert caps.connect_account
    assert not caps.publish_content  # Not yet implemented
    assert not caps.get_analytics  # Not yet implemented


def test_pinterest_health_check():
    """Test Pinterest health check."""
    connector = PinterestConnector()

    result = connector.health_check()

    assert result["success"]
    assert result["platform"] == "pinterest"
    assert result["status"] == "available"
    assert "details" in result


def test_pinterest_account_status_default():
    """Test Pinterest account status when not initialized."""
    connector = PinterestConnector()

    result = connector.get_account_status("worker-123")

    assert result["success"]
    assert result["status"] == "not_started"
    assert not result["details"]["connected"]


def test_pinterest_start_onboarding():
    """Test starting Pinterest onboarding."""
    connector = PinterestConnector()

    result = connector.start_onboarding("worker-123")

    assert result["success"]
    assert result["status"] == "awaiting_human"
    assert result["platform"] == "pinterest"
    assert result["workflow_id"]
    assert result["current_step"] == 1
    assert result["requires_human_intervention"]
    assert result["checkpoint_type"] == "oauth_authorization_required"
    assert "instructions" in result


def test_pinterest_resume_onboarding_invalid_workflow():
    """Test resuming onboarding with invalid workflow ID."""
    connector = PinterestConnector()

    result = connector.resume_onboarding("invalid-workflow-id", {})

    assert not result["success"]
    assert "not found" in result["error"].lower()


def test_pinterest_resume_onboarding_step_two():
    """Test resuming onboarding progresses to step 2."""
    connector = PinterestConnector()

    # Start onboarding
    start_result = connector.start_onboarding("worker-123")
    workflow_id = start_result["workflow_id"]

    # Resume with oauth completion
    resume_result = connector.resume_onboarding(
        workflow_id,
        {"oauth_code": "test-code", "email": "user@example.com"},
    )

    assert resume_result["success"]
    assert resume_result["status"] == "awaiting_human"
    assert resume_result["current_step"] == 2
    assert resume_result["checkpoint_type"] == "email_verification_required"
    assert "instructions" in resume_result


def test_pinterest_resume_onboarding_step_three():
    """Test resuming onboarding progresses to step 3."""
    connector = PinterestConnector()

    # Start onboarding
    start_result = connector.start_onboarding("worker-123")
    workflow_id = start_result["workflow_id"]

    # Complete step 1
    step2_result = connector.resume_onboarding(
        workflow_id,
        {"oauth_code": "test-code", "email": "user@example.com"},
    )

    # Complete step 2
    step3_result = connector.resume_onboarding(
        workflow_id,
        {"email_verified": True},
    )

    assert step3_result["success"]
    assert step3_result["status"] == "awaiting_human"
    assert step3_result["current_step"] == 3
    assert step3_result["checkpoint_type"] == "manual_platform_step_required"


def test_pinterest_resume_onboarding_completes():
    """Test that onboarding completes after all steps."""
    connector = PinterestConnector()

    # Start onboarding
    start_result = connector.start_onboarding("worker-123")
    workflow_id = start_result["workflow_id"]

    # Complete step 1
    connector.resume_onboarding(
        workflow_id,
        {"oauth_code": "test-code", "email": "user@example.com"},
    )

    # Complete step 2
    connector.resume_onboarding(
        workflow_id,
        {"email_verified": True},
    )

    # Complete step 3
    final_result = connector.resume_onboarding(
        workflow_id,
        {"account_configured": True},
    )

    assert final_result["success"]
    assert final_result["status"] == "completed"
    assert not final_result["requires_human_intervention"]


def test_pinterest_connect_account():
    """Test connecting Pinterest account."""
    connector = PinterestConnector()

    result = connector.connect_account("worker-123", {"oauth_code": "test-code"})

    assert result["success"]
    assert result["status"] == "connected"


def test_pinterest_connect_account_missing_oauth():
    """Test connect account fails without OAuth code."""
    connector = PinterestConnector()

    result = connector.connect_account("worker-123", {})

    assert not result["success"]
    assert "authorization code" in result["error"].lower()
