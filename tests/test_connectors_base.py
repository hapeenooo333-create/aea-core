"""Tests for platform connector base classes and registry."""

import pytest

from app.services.connectors.base import BaseConnector, ConnectorCapabilities
from app.services.connectors.registry import ConnectorRegistry


class MockConnector(BaseConnector):
    """Mock connector for testing."""

    @property
    def platform(self) -> str:
        """Get platform name."""
        return "mock_platform"

    @property
    def capabilities(self) -> ConnectorCapabilities:
        """Get connector capabilities."""
        return ConnectorCapabilities(
            platform="mock_platform",
            health_check=True,
            account_status=True,
            onboarding=False,
        )

    def health_check(self) -> dict:
        """Mock health check."""
        return {"status": "healthy", "platform": "mock_platform"}

    def get_account_status(self) -> dict:
        """Mock account status."""
        return {"status": "not_started"}

    def start_onboarding(self, worker_id: str) -> dict:
        """Mock start onboarding."""
        raise NotImplementedError("Onboarding not supported")

    def resume_onboarding(self, workflow_id: str, human_input: dict) -> dict:
        """Mock resume onboarding."""
        raise NotImplementedError("Onboarding not supported")


def test_connector_registry_register():
    """Test registering a connector."""
    registry = ConnectorRegistry()
    connector = MockConnector()

    result = registry.register(connector)

    assert result["success"]
    assert result["platform"] == "mock_platform"


def test_connector_registry_get():
    """Test retrieving a registered connector."""
    registry = ConnectorRegistry()
    connector = MockConnector()
    registry.register(connector)

    retrieved = registry.get("mock_platform")

    assert retrieved is not None
    assert retrieved.platform == "mock_platform"


def test_connector_registry_get_nonexistent():
    """Test retrieving a nonexistent connector."""
    registry = ConnectorRegistry()

    result = registry.get("nonexistent_platform")

    assert result is None


def test_connector_registry_list_platforms():
    """Test listing registered platforms."""
    registry = ConnectorRegistry()
    connector1 = MockConnector()
    registry.register(connector1)

    platforms = registry.list_platforms()

    assert "mock_platform" in platforms


def test_connector_registry_has_connector():
    """Test checking connector existence."""
    registry = ConnectorRegistry()
    connector = MockConnector()
    registry.register(connector)

    assert registry.has_connector("mock_platform")
    assert not registry.has_connector("nonexistent")


def test_connector_registry_get_capabilities():
    """Test retrieving connector capabilities."""
    registry = ConnectorRegistry()
    connector = MockConnector()
    registry.register(connector)

    capabilities = registry.get_capabilities("mock_platform")

    assert capabilities is not None
    assert capabilities.platform == "mock_platform"
    assert capabilities.health_check
    assert not capabilities.onboarding


def test_connector_registry_get_capabilities_dict():
    """Test retrieving capabilities as dictionary."""
    registry = ConnectorRegistry()
    connector = MockConnector()
    registry.register(connector)

    caps_dict = registry.get_capabilities_dict("mock_platform")

    assert caps_dict is not None
    assert caps_dict["platform"] == "mock_platform"
    assert caps_dict["health_check"]


def test_connector_registry_list_capabilities():
    """Test listing all capabilities."""
    registry = ConnectorRegistry()
    connector = MockConnector()
    registry.register(connector)

    all_caps = registry.list_capabilities()

    assert "mock_platform" in all_caps
    assert all_caps["mock_platform"]["platform"] == "mock_platform"


def test_connector_capabilities_to_dict():
    """Test converting capabilities to dictionary."""
    caps = ConnectorCapabilities(
        platform="test_platform",
        health_check=True,
        onboarding=True,
    )

    caps_dict = caps.to_dict()

    assert caps_dict["platform"] == "test_platform"
    assert caps_dict["health_check"]
    assert caps_dict["onboarding"]
