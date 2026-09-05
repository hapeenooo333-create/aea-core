"""Memory utilities for platform connectors in Sprint 7.2-B.

This module provides convenience functions for recording platform connector
events in agent memory using the existing Memory Engine infrastructure.

Recorded events include connector operations and onboarding milestones.
Sensitive data (credentials, tokens, OTPs) is never recorded.
"""

from __future__ import annotations

from typing import Any

from .memory_engine import AtlasMemoryEngine


class ConnectorMemoryRecorder:
    """Record connector-related events in agent memory."""

    def __init__(self, memory_engine: AtlasMemoryEngine | None = None) -> None:
        """Initialize the recorder.

        Args:
            memory_engine: Optional AtlasMemoryEngine instance.
                          If not provided, a new one will be created.
        """
        self._memory_engine = memory_engine or AtlasMemoryEngine()

    def record_onboarding_started(
        self,
        worker_id: str,
        platform: str,
        mission_id: str | None = None,
    ) -> dict[str, Any]:
        """Record that platform onboarding has started.

        Args:
            worker_id: Worker identifier.
            platform: Platform name.
            mission_id: Associated mission ID (optional).

        Returns:
            Result from memory engine.
        """
        content = {
            "event": "onboarding_started",
            "platform": platform,
            "mission_id": mission_id,
        }
        return self._memory_engine.store_memory(worker_id, "platform_onboarding", content)

    def record_onboarding_paused(
        self,
        worker_id: str,
        platform: str,
        checkpoint_type: str,
        workflow_id: str | None = None,
        mission_id: str | None = None,
    ) -> dict[str, Any]:
        """Record that onboarding workflow has paused for human intervention.

        Args:
            worker_id: Worker identifier.
            platform: Platform name.
            checkpoint_type: Type of checkpoint (oauth_authorization_required, etc.).
            workflow_id: Onboarding workflow ID (optional).
            mission_id: Associated mission ID (optional).

        Returns:
            Result from memory engine.
        """
        content = {
            "event": "onboarding_paused",
            "platform": platform,
            "checkpoint_type": checkpoint_type,
            "workflow_id": workflow_id,
            "mission_id": mission_id,
        }
        return self._memory_engine.store_memory(worker_id, "platform_onboarding", content)

    def record_checkpoint_completed(
        self,
        worker_id: str,
        platform: str,
        checkpoint_type: str,
        workflow_id: str | None = None,
        mission_id: str | None = None,
    ) -> dict[str, Any]:
        """Record that a human intervention checkpoint has been completed.

        Args:
            worker_id: Worker identifier.
            platform: Platform name.
            checkpoint_type: Type of checkpoint.
            workflow_id: Onboarding workflow ID (optional).
            mission_id: Associated mission ID (optional).

        Returns:
            Result from memory engine.
        """
        content = {
            "event": "checkpoint_completed",
            "platform": platform,
            "checkpoint_type": checkpoint_type,
            "workflow_id": workflow_id,
            "mission_id": mission_id,
        }
        return self._memory_engine.store_memory(worker_id, "platform_onboarding", content)

    def record_onboarding_completed(
        self,
        worker_id: str,
        platform: str,
        workflow_id: str | None = None,
        mission_id: str | None = None,
    ) -> dict[str, Any]:
        """Record that platform onboarding has been completed successfully.

        Args:
            worker_id: Worker identifier.
            platform: Platform name.
            workflow_id: Onboarding workflow ID (optional).
            mission_id: Associated mission ID (optional).

        Returns:
            Result from memory engine.
        """
        content = {
            "event": "onboarding_completed",
            "platform": platform,
            "workflow_id": workflow_id,
            "mission_id": mission_id,
        }
        return self._memory_engine.store_memory(worker_id, "platform_onboarding", content)

    def record_platform_connected(
        self,
        worker_id: str,
        platform: str,
        external_account_id: str | None = None,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        """Record that a platform account has been connected.

        Args:
            worker_id: Worker identifier.
            platform: Platform name.
            external_account_id: ID on the external platform (optional).
            display_name: Display name on the platform (optional).

        Returns:
            Result from memory engine.
        """
        content = {
            "event": "platform_connected",
            "platform": platform,
            "external_account_id": external_account_id,
            "display_name": display_name,
        }
        return self._memory_engine.store_memory(worker_id, "platform_connection", content)

    def record_connector_error(
        self,
        worker_id: str,
        platform: str,
        error_message: str,
        action_type: str | None = None,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        """Record a connector error event.

        Args:
            worker_id: Worker identifier.
            platform: Platform name.
            error_message: Description of the error (non-sensitive details only).
            action_type: Type of action that failed (optional).
            workflow_id: Associated workflow ID (optional).

        Returns:
            Result from memory engine.
        """
        content = {
            "event": "connector_error",
            "platform": platform,
            "error_message": error_message,
            "action_type": action_type,
            "workflow_id": workflow_id,
        }
        return self._memory_engine.store_memory(worker_id, "connector_event", content)

    def record_action_dispatched(
        self,
        worker_id: str,
        platform: str,
        action_type: str,
        mission_id: str | None = None,
    ) -> dict[str, Any]:
        """Record that a connector action has been dispatched.

        Args:
            worker_id: Worker identifier.
            platform: Platform name.
            action_type: Type of action dispatched.
            mission_id: Associated mission ID (optional).

        Returns:
            Result from memory engine.
        """
        content = {
            "event": "action_dispatched",
            "platform": platform,
            "action_type": action_type,
            "mission_id": mission_id,
        }
        return self._memory_engine.store_memory(worker_id, "connector_event", content)
