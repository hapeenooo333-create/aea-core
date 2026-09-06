"""Action execution service for Sprint 4.1.

This module converts simple agent decisions into lightweight executable
actions. The implementation is intentionally small and defensive so it can be
used safely even when the supporting services or database client are
unavailable.
"""

from __future__ import annotations

from typing import Any

from .memory_engine import AtlasMemoryEngine


# Action risk classification
SAFE_ACTIONS = {
    "research",
    "analysis",
    "content_draft",
    "memory_store",
    "log",
    "check_platform_status",
    "health_check",
}

SENSITIVE_ACTIONS = {
    "create_account",
    "connect_platform",
    "publish_content",
    "send_message",
    "modify_external_account",
    "start_platform_onboarding",
}

# Platform connector workflow actions (may require approval or human intervention)
CONNECTOR_ACTIONS = {
    "start_platform_onboarding",
    "resume_platform_onboarding",
    "connect_platform",
    "check_platform_status",
    "publish_content",
}


class ActionEngine:
    """Translate action requests into lightweight execution results."""

    def __init__(self, owner_id: str | None = None) -> None:
        """Initialize the engine with its supporting services.

        Args:
            owner_id: Canonical owner identifier (auth.users.id). When provided,
                memory operations will be scoped to this owner for RLS enforcement.
        """

        self._owner_id = owner_id
        self._memory_engine = AtlasMemoryEngine()

    def classify_action(self, action_type: str) -> dict[str, Any]:
        """Classify an action by risk level.

        Args:
            action_type: The action type to classify.

        Returns:
            Dictionary with risk classification and approval requirement.
        """
        if action_type in SAFE_ACTIONS:
            return {
                "risk_level": "safe",
                "requires_approval": False,
            }

        if action_type in SENSITIVE_ACTIONS:
            return {
                "risk_level": "sensitive",
                "requires_approval": True,
            }

        # Default to moderate risk
        return {
            "risk_level": "moderate",
            "requires_approval": False,
        }

    def create_action_envelope(
        self,
        action_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a structured action envelope with risk classification.

        Args:
            action_type: The type of action to execute.
            payload: Action-specific payload data.

        Returns:
            Structured action envelope with metadata.
        """
        classification = self.classify_action(action_type)

        return {
            "action_type": action_type,
            "risk_level": classification["risk_level"],
            "requires_approval": classification["requires_approval"],
            "payload": payload,
        }

    def execute_action(self, action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a supported action request.

        Args:
            action_type: The action category to execute, such as ``log`` or
                ``memory_store``.
            payload: A dictionary containing the action-specific data.

        Returns:
            A structured dictionary describing the execution result.
        """

        if not action_type:
            return {"success": False, "error": "Action type is required"}

        try:
            if action_type == "log":
                return self._handle_log(payload)
            if action_type == "memory_store":
                return self._handle_memory_store(payload)
            if action_type == "database_query":
                return self._handle_database_query(payload)
            if action_type == "api_call":
                return self._handle_api_call(payload)
            if action_type == "research":
                return self._handle_research(payload)
            if action_type == "analysis":
                return self._handle_analysis(payload)
            if action_type == "content_draft":
                return self._handle_content_draft(payload)
            if action_type == "check_platform_status":
                return self._handle_check_platform_status(payload)
            if action_type == "health_check":
                return self._handle_health_check(payload)
            if action_type == "start_platform_onboarding":
                return self._handle_start_platform_onboarding(payload)
            if action_type == "resume_platform_onboarding":
                return self._handle_resume_platform_onboarding(payload)
            if action_type == "connect_platform":
                return self._handle_connect_platform(payload)
            if action_type == "publish_content":
                return self._handle_publish_content(payload)

            return {"success": False, "error": f"Unsupported action type: {action_type}"}
        except Exception as exc:  # pragma: no cover - defensive runtime handling
            return {"success": False, "error": str(exc)}

    def _handle_log(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a simple logging action."""

        message = payload.get("message") if isinstance(payload, dict) else None
        result = {"message": message or "Action executed"}
        return {"success": True, "action": "log", "result": result}

    def _handle_memory_store(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Store a memory entry through the Atlas memory engine."""

        worker_id = payload.get("worker_id") if isinstance(payload, dict) else None
        content = payload.get("content") if isinstance(payload, dict) else {}
        memory_type = payload.get("memory_type") or "action"

        if not worker_id:
            return {"success": False, "error": "worker_id is required for memory storage"}

        response = self._memory_engine.store_memory(worker_id, memory_type, content, owner_id=self._owner_id)
        if response.get("success"):
            return {"success": True, "action": "memory_store", "result": response}

        return {"success": False, "action": "memory_store", "error": response.get("error", "Memory storage failed")}

    def _handle_database_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Provide a safe placeholder for future database queries."""

        query = payload.get("query") if isinstance(payload, dict) else None
        return {
            "success": True,
            "action": "database_query",
            "result": {
                "message": "Database query placeholder",
                "query": query or "",
            },
        }

    def _handle_api_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Provide a safe placeholder for future external API calls."""

        endpoint = payload.get("endpoint") if isinstance(payload, dict) else None
        return {
            "success": True,
            "action": "api_call",
            "result": {
                "message": "API call placeholder",
                "endpoint": endpoint or "",
            },
        }

    def _handle_research(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a research action."""

        query = payload.get("query") if isinstance(payload, dict) else None
        return {
            "success": True,
            "action": "research",
            "result": {
                "message": "Research action executed",
                "query": query or "",
            },
        }

    def _handle_analysis(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle an analysis action."""

        query = payload.get("query") if isinstance(payload, dict) else None
        return {
            "success": True,
            "action": "analysis",
            "result": {
                "message": "Analysis action executed",
                "query": query or "",
            },
        }

    def _handle_content_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a content draft action."""

        topic = payload.get("topic") if isinstance(payload, dict) else None
        return {
            "success": True,
            "action": "content_draft",
            "result": {
                "message": "Content draft action executed",
                "topic": topic or "",
            },
        }

    def _handle_check_platform_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a platform status check action.

        This is a safe, read-only operation that does not require approval.
        """
        platform = payload.get("platform") if isinstance(payload, dict) else None
        return {
            "success": True,
            "action": "check_platform_status",
            "result": {
                "message": "Platform status check placeholder",
                "platform": platform or "",
                "status": "not_configured",
            },
        }

    def _handle_health_check(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a health check action.

        This is a safe, read-only operation that does not require approval.
        """
        return {
            "success": True,
            "action": "health_check",
            "result": {
                "message": "Health check executed",
                "status": "healthy",
            },
        }

    def _handle_start_platform_onboarding(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a start platform onboarding action.

        This action requires approval and will be handled by the worker runtime
        to dispatch to the appropriate connector. This is just a placeholder.
        """
        platform = payload.get("platform") if isinstance(payload, dict) else None
        return {
            "success": False,
            "error": "start_platform_onboarding must be executed through worker runtime",
            "requires_dispatch": True,
            "action": "start_platform_onboarding",
            "platform": platform,
        }

    def _handle_resume_platform_onboarding(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a resume platform onboarding action.

        This action resumes a paused onboarding workflow after human intervention.
        """
        workflow_id = payload.get("workflow_id") if isinstance(payload, dict) else None
        return {
            "success": False,
            "error": "resume_platform_onboarding must be executed through worker runtime",
            "requires_dispatch": True,
            "action": "resume_platform_onboarding",
            "workflow_id": workflow_id,
        }

    def _handle_connect_platform(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a connect platform action.

        This action requires approval and will be handled by the worker runtime.
        """
        platform = payload.get("platform") if isinstance(payload, dict) else None
        return {
            "success": False,
            "error": "connect_platform must be executed through worker runtime",
            "requires_dispatch": True,
            "action": "connect_platform",
            "platform": platform,
        }

    def _handle_publish_content(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle a publish content action.

        This action requires approval and will be handled by the worker runtime.
        """
        platform = payload.get("platform") if isinstance(payload, dict) else None
        return {
            "success": False,
            "error": "publish_content must be executed through worker runtime",
            "requires_dispatch": True,
            "action": "publish_content",
            "platform": platform,
        }


__all__ = ["ActionEngine"]
