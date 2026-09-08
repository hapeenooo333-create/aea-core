"""P1-7B employee vertical slice tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.approval_gateway import ApprovalGateway
from app.services.employee_vertical_slice import EmployeeVerticalSlice
from app.services.mission_execution_service import MissionExecutionService
from app.services.p1_7_contracts import sanitize_payload
from app.services.stores.platform_connection_store import PlatformConnectionStore


def _slice(owner: str = "user-a") -> EmployeeVerticalSlice:
    return EmployeeVerticalSlice(
        owner,
        connection_store=PlatformConnectionStore(client=None),
        execution_service=MissionExecutionService(client=None),
        approval_gateway=ApprovalGateway(client=None),
    )


def test_pinterest_status_is_real_read_and_reports_not_connected():
    employee = _slice()
    result = employee.run("Check my Pinterest account status", mission_id="mission-status")

    assert result["success"] is True
    assert result["status"] == "COMPLETE"
    report = result["report"]
    assert report["selected_tools"] == ["pinterest.get_account_status"]
    assert report["results"][0]["status"] == "not_started"
    assert report["discovered_capabilities"]["tools"]
    assert report["execution_id"]


def test_onboarding_creates_durable_approval_and_resumes_to_human_checkpoint():
    employee = _slice()
    pending = employee.run("Connect my Pinterest account", mission_id="mission-connect")

    assert pending["success"] is False
    assert pending["status"] == "WAIT_FOR_APPROVAL"
    approval_id = pending["report"]["resume_information"]["approval_request_id"]
    assert approval_id

    approved = employee._approvals.approve_request(approval_id, approved_by="user-a")
    assert approved["success"] is True
    resumed = employee.resume_approval(approval_id)
    assert resumed["status"] == "awaiting_human_intervention"
    assert resumed["result"]["platform"] == "pinterest"

    execution_id = pending["report"]["resume_information"]["execution_id"]
    execution = employee._execution.get_execution(execution_id, owner_id="user-a")
    assert execution["status"] == "WAITING_INPUT"
    assert employee._execution.get_execution(execution_id, owner_id="user-b") is None


def test_capabilities_are_owner_scoped_and_connection_status_is_not_faked():
    employee = _slice("user-a")
    employee._connections.upsert("user-a", "pinterest", status="connected", scopes=[])
    discovered = employee.discover_capabilities()
    names = {tool["tool_name"] for tool in discovered["tools"]}
    assert "pinterest.get_account_status" in names

    other = _slice("user-b")
    other_names = {tool["tool_name"] for tool in other.discover_capabilities()["tools"]}
    assert "pinterest.get_account_status" in other_names
    assert employee._connections.get("user-b", "pinterest") is None


def test_secret_sanitization_is_recursive_and_report_safe():
    value = sanitize_payload({"nested": {"access_token": "secret", "ok": True}, "password": "pw"})
    assert value == {"nested": {"ok": True}}
    result = _slice().run("Check my Pinterest status", metadata={"content_inputs": {"api_key": "secret"}})
    assert "secret" not in str(result["report"])


def test_unknown_tool_cannot_enter_the_plan():
    employee = _slice()
    validation = employee._validator.validate([{"tool_name": "arbitrary_function", "input": {}}], discovered=employee.discover_capabilities())
    assert validation["success"] is False
    assert "unknown tool" in validation["errors"][0]


def test_orchestrator_requires_an_authenticated_owner_for_objective_execution():
    from app.services.agent_orchestrator import AgentOrchestrator

    result = AgentOrchestrator().run_objective("Check Pinterest")
    assert result == {"success": False, "status": "FAIL", "error": "Authenticated owner is required"}
