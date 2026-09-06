"""Connector Registry for managing platform connector instances in Sprint 7.2-B.

The registry is responsible for:
- Registering connectors
- Retrieving connectors by platform name
- Listing supported platforms
- Checking connector availability
- Exposing connector capabilities
"""

from __future__ import annotations

from typing import Any

from .base import BaseConnector, ConnectorCapabilities


class ConnectorRegistry:
    """Registry for managing platform connector instances."""

    def __init__(self) -> None:
        """Initialize the connector registry."""
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> dict[str, Any]:
        """Register a platform connector.

        Args:
            connector: The BaseConnector instance to register.

        Returns:
            Dictionary with success status.
        """
        if not isinstance(connector, BaseConnector):
            return {"success": False, "error": "Connector must extend BaseConnector"}

        platform = connector.platform
        if not platform or not isinstance(platform, str):
            return {"success": False, "error": "Connector platform name is invalid"}

        self._connectors[platform.lower()] = connector
        return {
            "success": True,
            "message": f"Registered connector for platform '{platform}'",
            "platform": platform,
        }

    def get(self, platform: str) -> BaseConnector | None:
        """Retrieve a connector by platform name.

        Args:
            platform: Platform name (e.g., 'pinterest').

        Returns:
            The BaseConnector instance, or None if not found.
        """
        if not platform:
            return None
        return self._connectors.get(platform.lower())

    def list_platforms(self) -> list[str]:
        """List all supported platforms.

        Returns:
            List of platform names that have registered connectors.
        """
        return list(self._connectors.keys())

    def has_connector(self, platform: str) -> bool:
        """Check whether a connector is registered for a platform.

        Args:
            platform: Platform name to check.

        Returns:
            True if a connector exists for this platform.
        """
        return platform.lower() in self._connectors

    def get_capabilities(self, platform: str) -> ConnectorCapabilities | None:
        """Get the capabilities of a platform's connector.

        Args:
            platform: Platform name.

        Returns:
            ConnectorCapabilities instance, or None if connector not found.
        """
        connector = self.get(platform)
        if connector:
            return connector.capabilities
        return None

    def get_capabilities_dict(self, platform: str) -> dict[str, Any] | None:
        """Get the capabilities of a platform's connector as a dictionary.

        Args:
            platform: Platform name.

        Returns:
            Dictionary representation of capabilities, or None if not found.
        """
        capabilities = self.get_capabilities(platform)
        if capabilities:
            return capabilities.to_dict()
        return None

    def list_capabilities(self) -> dict[str, Any]:
        """List capabilities for all registered connectors.

        Returns:
            Dictionary mapping platform names to their capabilities.
        """
        result = {}
        for platform in self.list_platforms():
            caps_dict = self.get_capabilities_dict(platform)
            if caps_dict:
                result[platform] = caps_dict
        return result
