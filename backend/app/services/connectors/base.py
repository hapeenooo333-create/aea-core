"""Base connector abstraction for platform integrations in Sprint 7.2-B.

This module defines the common interface that all platform connectors must implement.
Platform-specific logic is isolated within individual connector implementations.

The base interface supports operations for:
- Health checking
- Account status querying
- Onboarding workflows
- Account connection
- Content publishing
- Analytics retrieval
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


@dataclass
class ConnectorCapabilities:
    """Describe the capabilities of a platform connector."""

    platform: str
    """Platform name (e.g., 'pinterest')."""

    health_check: bool = True
    """Whether the connector can perform health checks."""

    account_status: bool = False
    """Whether the connector can query account status."""

    onboarding: bool = False
    """Whether the connector supports account onboarding workflows."""

    connect_account: bool = False
    """Whether the connector can establish account connections."""

    disconnect_account: bool = False
    """Whether the connector can disconnect accounts."""

    publish_content: bool = False
    """Whether the connector can publish content to the platform."""

    get_analytics: bool = False
    """Whether the connector can retrieve platform analytics."""

    human_intervention_capable: bool = True
    """Whether the connector supports pause/resume with human checkpoints."""

    supported_checkpoint_types: list[str] = field(default_factory=lambda: [
        "otp_required",
        "captcha_required",
        "email_verification_required",
        "oauth_authorization_required",
        "identity_verification_required",
        "kyc_required",
        "payment_confirmation_required",
        "manual_platform_step_required",
    ])
    """Checkpoint types this connector can handle."""

    def to_dict(self) -> dict[str, Any]:
        """Convert capabilities to a dictionary.

        Returns:
            Dictionary representation of capabilities.
        """
        return {
            "platform": self.platform,
            "health_check": self.health_check,
            "account_status": self.account_status,
            "onboarding": self.onboarding,
            "connect_account": self.connect_account,
            "disconnect_account": self.disconnect_account,
            "publish_content": self.publish_content,
            "get_analytics": self.get_analytics,
            "human_intervention_capable": self.human_intervention_capable,
            "supported_checkpoint_types": self.supported_checkpoint_types,
        }


class BaseConnector(ABC):
    """Abstract base class for all platform connectors.

    Subclasses must implement all abstract methods while following the
    constraint that no sensitive credentials or authentication data should
    be stored in mission memory or logs.
    """

    def __init__(self) -> None:
        """Initialize the connector."""
        self._connector_id = str(uuid4())

    @property
    def connector_id(self) -> str:
        """Get the unique connector instance ID.

        Returns:
            Unique identifier for this connector instance.
        """
        return self._connector_id

    @property
    @abstractmethod
    def platform(self) -> str:
        """Get the platform name this connector targets.

        Returns:
            Platform name (e.g., 'pinterest').
        """

    @property
    @abstractmethod
    def capabilities(self) -> ConnectorCapabilities:
        """Get the connector's capabilities.

        Returns:
            ConnectorCapabilities describing supported operations.
        """

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Perform a health check on the platform connection.

        Returns:
            Dictionary with status and details:
            {
                "platform": "pinterest",
                "status": "available" | "unavailable" | "not_configured",
                "details": {}
            }
        """

    @abstractmethod
    def get_account_status(self) -> dict[str, Any]:
        """Retrieve the current account status.

        Returns:
            Dictionary with account state:
            {
                "status": "not_started" | "onboarding" | "awaiting_human" |
                          "connected" | "needs_reconnect" | "failed",
                "details": {}
            }
        """

    @abstractmethod
    def start_onboarding(self, worker_id: str) -> dict[str, Any]:
        """Start a platform onboarding workflow.

        Args:
            worker_id: Identifier of the worker initiating onboarding.

        Returns:
            Dictionary describing workflow state:
            {
                "status": "in_progress" | "awaiting_human" | "completed" | "failed",
                "workflow_id": "...",
                "platform": "pinterest",
                "next_step": "...",
                "requires_human_intervention": bool,
                "checkpoint_type": "oauth_authorization_required" | None,
                "instructions": "...",
                "error": None | "..."
            }
        """

    @abstractmethod
    def resume_onboarding(self, workflow_id: str, human_input: dict[str, Any]) -> dict[str, Any]:
        """Resume an onboarding workflow after human completion of a checkpoint.

        Args:
            workflow_id: Identifier of the workflow to resume.
            human_input: Data provided by human completing the checkpoint.

        Returns:
            Dictionary describing resumed workflow state (same format as start_onboarding).
        """

    def connect_account(self, worker_id: str, auth_data: dict[str, Any]) -> dict[str, Any]:
        """Establish a connection to a platform account.

        Default implementation raises NotImplementedError. Subclasses should override
        if connect_account capability is True.

        Args:
            worker_id: Identifier of the worker.
            auth_data: Authorization data for connecting (format varies by platform).

        Returns:
            Dictionary with connection result.
        """
        raise NotImplementedError(f"connect_account not implemented for {self.platform}")

    def disconnect_account(self, worker_id: str) -> dict[str, Any]:
        """Disconnect from a platform account.

        Default implementation raises NotImplementedError. Subclasses should override
        if disconnect_account capability is True.

        Args:
            worker_id: Identifier of the worker.

        Returns:
            Dictionary with disconnection result.
        """
        raise NotImplementedError(f"disconnect_account not implemented for {self.platform}")

    def publish_content(self, worker_id: str, content: dict[str, Any]) -> dict[str, Any]:
        """Publish content to the platform.

        Default implementation raises NotImplementedError. Subclasses should override
        if publish_content capability is True.

        Args:
            worker_id: Identifier of the worker.
            content: Content dictionary with platform-specific structure.

        Returns:
            Dictionary with publish result.
        """
        raise NotImplementedError(f"publish_content not implemented for {self.platform}")

    def get_analytics(self, worker_id: str) -> dict[str, Any]:
        """Retrieve analytics data from the platform.

        Default implementation raises NotImplementedError. Subclasses should override
        if get_analytics capability is True.

        Args:
            worker_id: Identifier of the worker.

        Returns:
            Dictionary with analytics data.
        """
        raise NotImplementedError(f"get_analytics not implemented for {self.platform}")
