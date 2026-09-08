"""Focused P1-7A contract tests; no external side effects are performed."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.capability_discovery import CapabilityDiscovery
from app.services.connectors.base import BaseConnector, ConnectorCapabilities
from app.services.connectors.registry import ConnectorRegistry
from app.services.p1_7_contracts import (
    BoundedDecisionLoop,
    ObjectiveParser,
    Observation,
    ToolContract,
    classify_approval,
)
from app.services.plan_validator import PlanValidator
from app.services.tool_registry import ToolRegistry
from app.services.tool_safety import SafeActionExecutor, ToolValidator
from app.services.action_engine import ActionEngine


class _Connector(BaseConnector):
    @property
    def platform(self) -> str:
        return "pinterest"

    @property
    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(platform="pinterest", account_status=True)

    def health_check(self) -> dict:
        return {"success": True}

    def get_account_status(self) -> dict:
        return {"status": "connected"}

    def start_onboarding(self, worker_id: str) -> dict:
        raise NotImplementedError

    def resume_onboarding(self, workflow_id: str, human_input: dict) -> dict:
        raise NotImplementedError


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_contract(
        ToolContract(
            tool_name="pinterest.list_boards",
            description="List boards",
            input_schema={"type": "object", "additionalProperties": False},
            capability="account_status",
            platform="pinterest",
            operation="list_boards",
            requires_connection=True,
            risk_level="READ_ONLY",
        ),
        required_scopes=["boards:read"],
    )
    registry.register_tool(
        "safe_echo",
        "Echo",
        schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
            "additionalProperties": False,
        },
    )
    return registry


def test_tool_registration_exposes_canonical_contract():
    tool = _registry().get_tool("pinterest.list_boards")["tool"]
    assert tool["tool_name"] == "pinterest.list_boards"
    assert tool["version"] == "1.0"
    assert tool["input_schema"]["type"] == "object"
    assert tool["platform"] == "pinterest"


def test_tool_schema_validation_rejects_unknown_and_invalid_payloads():
    registry = _registry()
    validator = ToolValidator(registry, ActionEngine())
    try:
        validator.validate_and_prepare("safe_echo", {"message": 3})
        assert False, "invalid type should be rejected"
    except Exception as exc:
        assert exc.reason == "VALIDATION"
    try:
        validator.validate_and_prepare("safe_echo", {"message": "ok", "extra": True})
        assert False, "unknown field should be rejected"
    except Exception as exc:
        assert exc.reason == "VALIDATION"


def test_capability_discovery_is_connection_and_scope_aware():
    connectors = ConnectorRegistry()
    connectors.register(_Connector())
    discovery = CapabilityDiscovery(_registry(), connectors)
    disconnected = discovery.discover("user-a", lambda owner, platform: {"status": "disconnected"})
    assert not any(tool["platform"] == "pinterest" for tool in disconnected["tools"])
    connected = discovery.discover("user-a", lambda owner, platform: {"status": "connected", "scopes": ["boards:read"]})
    assert [tool["tool_name"] for tool in connected["tools"] if tool["platform"] == "pinterest"] == ["pinterest.list_boards"]


def test_capability_discovery_does_not_leak_between_users():
    connectors = ConnectorRegistry()
    connectors.register(_Connector())
    discovery = CapabilityDiscovery(_registry(), connectors)
    lookup = lambda owner, platform: {"status": "connected", "scopes": ["boards:read"]} if owner == "user-a" else None
    assert any(tool["platform"] == "pinterest" for tool in discovery.discover("user-a", lookup)["tools"])
    assert not any(tool["platform"] == "pinterest" for tool in discovery.discover("user-b", lookup)["tools"])


def test_objective_parser_preserves_goal_and_optional_structure():
    objective = ObjectiveParser().parse("List my boards", {"success_criteria": ["return boards"]})
    assert objective.goal == "List my boards"
    assert objective.success_criteria == ["return boards"]
    assert objective.desired_outcome is None


def test_plan_validator_rejects_unknown_tool_and_invalid_schema():
    validator = PlanValidator(_registry())
    unknown = validator.validate([{"tool_name": "missing", "input": {}}])
    assert not unknown["success"]
    invalid = validator.validate([{"tool_name": "safe_echo", "input": {}}])
    assert not invalid["success"]


def test_plan_validator_rejects_unavailable_tool():
    validator = PlanValidator(_registry())
    result = validator.validate([{"tool_name": "safe_echo", "input": {"message": "ok"}}], available_tools=set())
    assert not result["success"]
    assert "not available" in result["errors"][0]


def test_approval_classification_cannot_bypass_writes_or_destructive_actions():
    assert classify_approval(ToolContract("read", risk_level="READ_ONLY")) == "READ_ONLY"
    assert classify_approval(ToolContract("write", risk_level="WRITE_EXTERNAL")) == "REQUIRES_APPROVAL"
    assert classify_approval(ToolContract("delete", risk_level="DESTRUCTIVE")) == "ALWAYS_APPROVE"


def test_observation_sanitizes_secrets():
    observation = Observation("read", {"access_token": "secret", "boards": []}, True)
    assert "access_token" not in observation.to_dict()["result"]


def test_retry_classification_remains_the_existing_bounded_contract():
    from app.services.retry_classifier import classify_failure
    assert classify_failure("permission denied").retryable is False
    assert classify_failure("timeout").max_retries > 0


def test_bounded_next_decision_loop_stops():
    loop = BoundedDecisionLoop(max_decisions=2)
    assert loop.allow_next()
    assert loop.allow_next()
    assert not loop.allow_next()


def test_tool_payload_sanitization_is_applied_before_execution():
    registry = ToolRegistry()
    registry.register_tool("echo", "Echo")
    prepared = ToolValidator(registry, ActionEngine()).validate_and_prepare(
        "echo", {"message": "ok", "nested": {"refresh_token": "secret"}}
    )
    assert "refresh_token" not in prepared["payload"]["nested"]


def test_safe_executor_forwards_only_sanitized_payload():
    registry = ToolRegistry()
    registry.register_tool("publish_content", "Publish content")
    validator = ToolValidator(registry, ActionEngine())

    class Runtime:
        def __init__(self):
            self.payload = None

        def execute_action_with_approval(self, mission_id, action_type, payload):
            self.payload = payload
            return {"success": True}

    runtime = Runtime()
    executor = SafeActionExecutor(validator, runtime)
    result = executor.execute(
        "publish_content",
        {"message": "ok", "access_token": "secret"},
        "mission-1",
    )

    assert result["success"]
    assert runtime.payload == {"message": "ok"}


def test_scoped_client_is_preserved_by_worker_runtime():
    from app.services.worker_runtime import WorkerRuntime

    scoped_client = object()
    runtime = WorkerRuntime(owner_id="user-a", client=scoped_client)
    assert runtime._employee_engine._execution_service._explicit_client is scoped_client
    assert runtime._employee_engine._mission_engine._client is scoped_client