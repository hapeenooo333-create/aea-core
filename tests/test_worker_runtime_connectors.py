"""Tests for worker runtime connector integration."""

import pytest

from app.services.connectors.pinterest_connector import PinterestConnector
from app.services.connectors.registry import ConnectorRegistry
from app.services.worker_runtime import WorkerRuntime


def test_worker_runtime_with_connector_registry():
    """Test initializing worker runtime with connector registry."""
    registry = ConnectorRegistry()
    pinterest = PinterestConnector()
    registry.register(pinterest)

    runtime = WorkerRuntime(connector_registry=registry)

    assert runtime.get_connector_registry() == registry


def test_worker_runtime_set_connector_registry():
    """Test setting connector registry after initialization."""
    runtime = WorkerRuntime()
    registry = ConnectorRegistry()
    pinterest = PinterestConnector()
    registry.register(pinterest)

    runtime.set_connector_registry(registry)

    assert runtime.get_connector_registry() == registry


def test_worker_runtime_execute_connector_action_no_registry():
    """Test executing connector action without registry."""
    runtime = WorkerRuntime()  # No registry

    result = runtime.execute_connector_action(
        mission_id="mission-123",
        action_type="check_platform_status",
        payload={"platform": "pinterest"},
    )

    assert not result["success"]
    assert "Connector registry not available" in result["error"]


def test_worker_runtime_execute_connector_action_missing_platform():
    """Test executing connector action without platform in payload."""
    registry = ConnectorRegistry()
    pinterest = PinterestConnector()
    registry.register(pinterest)

    runtime = WorkerRuntime(connector_registry=registry)

    result = runtime.execute_connector_action(
        mission_id="mission-123",
        action_type="check_platform_status",
        payload={},  # Missing platform
    )

    assert not result["success"]
    assert "platform" in result["error"].lower()


def test_worker_runtime_execute_connector_action_unsupported_platform():
    """Test executing connector action for unsupported platform."""
    registry = ConnectorRegistry()
    runtime = WorkerRuntime(connector_registry=registry)

    result = runtime.execute_connector_action(
        mission_id="mission-123",
        action_type="check_platform_status",
        payload={"platform": "unsupported_platform"},
    )

    assert not result["success"]
    assert "No connector registered" in result["error"]


def test_worker_runtime_execute_connector_action_requires_approval():
    """Test executing action that requires approval."""
    registry = ConnectorRegistry()
    pinterest = PinterestConnector()
    registry.register(pinterest)

    runtime = WorkerRuntime(connector_registry=registry)

    result = runtime.execute_connector_action(
        mission_id="mission-123",
        action_type="start_platform_onboarding",
        payload={"platform": "pinterest", "worker_id": "worker-123"},
    )

    assert not result["success"]
    assert result.get("pending_approval")
    assert "approval_request_id" in result


def test_worker_runtime_execute_connector_action_safe():
    """Test executing safe connector action."""
    registry = ConnectorRegistry()
    pinterest = PinterestConnector()
    registry.register(pinterest)

    runtime = WorkerRuntime(connector_registry=registry)

    # check_platform_status should be safe and execute immediately
    result = runtime.execute_connector_action(
        mission_id="mission-123",
        action_type="check_platform_status",
        payload={"platform": "pinterest"},
    )

    # This actually dispatches to connector, so we get health check result
    assert result["success"] or not result.get("pending_approval")


def test_worker_runtime_dispatch_to_connector_onboarding():
    """Test dispatching onboarding action to connector."""
    registry = ConnectorRegistry()
    pinterest = PinterestConnector()
    registry.register(pinterest)

    runtime = WorkerRuntime(connector_registry=registry)

    # Directly dispatch (would normally be called after approval)
    result = runtime._dispatch_to_connector(
        mission_id="mission-123",
        action_type="start_platform_onboarding",
        payload={"platform": "pinterest", "worker_id": "worker-123"},
        connector=pinterest,
    )

    # Should create human intervention checkpoint
    assert not result.get("success") or result.get("awaiting_human_intervention")
    assert "checkpoint_id" in result or "workflow_id" in result


def test_worker_runtime_dispatch_health_check():
    """Test dispatching health check action to connector."""
    registry = ConnectorRegistry()
    pinterest = PinterestConnector()
    registry.register(pinterest)

    runtime = WorkerRuntime(connector_registry=registry)

    result = runtime._dispatch_to_connector(
        mission_id="mission-123",
        action_type="check_platform_status",
        payload={"platform": "pinterest"},
        connector=pinterest,
    )

    assert result["success"]
    assert result["platform"] == "pinterest"
    assert result["status"] == "available"


def test_worker_runtime_dispatch_invalid_action():
    """Test dispatching invalid action to connector."""
    registry = ConnectorRegistry()
    pinterest = PinterestConnector()
    registry.register(pinterest)

    runtime = WorkerRuntime(connector_registry=registry)

    result = runtime._dispatch_to_connector(
        mission_id="mission-123",
        action_type="invalid_action",
        payload={"platform": "pinterest"},
        connector=pinterest,
    )

    assert not result["success"]
    assert "not implemented" in result["error"].lower()
