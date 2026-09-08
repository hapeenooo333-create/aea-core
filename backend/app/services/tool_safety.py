"""Deterministic tool validation and safety layer for P1-6.

The employee may propose an action, but execution must go through
ToolRegistry/ActionEngine. Unknown or malformed tool requests must
never execute. No arbitrary LLM-generated Python/function execution.
"""

from __future__ import annotations

from typing import Any

from .action_engine import ActionEngine
from .p1_7_contracts import sanitize_payload, validate_input_schema
from .tool_registry import ToolRegistry


class ToolSafetyError(Exception):
    """Raised when tool validation fails."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class ToolValidator:
    """Validates tool requests before execution.

    Ensures:
    1. Tool is registered in ToolRegistry
    2. Input matches expected schema (if available)
    3. Risk level and approval requirement are determined
    4. Only safe, validated tools are executed
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        action_engine: ActionEngine,
    ) -> None:
        """Initialize the validator.

        Args:
            tool_registry: The ToolRegistry instance for tool lookup.
            action_engine: The ActionEngine for risk classification.
        """
        self._tool_registry = tool_registry
        self._action_engine = action_engine

    def validate_and_prepare(
        self,
        action_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate a tool request and prepare it for execution.

        Args:
            action_type: The action/tool type to execute.
            payload: Action-specific payload data.

        Returns:
            Dictionary with validated action_type, payload, envelope,
            and execution_ready flag.

        Raises:
            ToolSafetyError: If validation fails (unknown tool, invalid input, etc.).
        """
        # 1. Check tool is registered
        tool_check = self._tool_registry.is_available(action_type)
        if not tool_check.get("available"):
            raise ToolSafetyError(
                f"Tool '{action_type}' is not registered or available [TOOL_NOT_FOUND]",
                reason="TOOL_NOT_FOUND",
            )

        # 2. Get tool metadata
        tool_response = self._tool_registry.get_tool(action_type)
        if not tool_response or not tool_response.get("success"):
            raise ToolSafetyError(
                f"Tool '{action_type}' metadata not found [TOOL_NOT_FOUND]",
                reason="TOOL_NOT_FOUND",
            )
        tool_info = tool_response.get("tool", {})

        # 3. Remove forbidden credentials before validation and execution.
        safe_payload = sanitize_payload(payload)
        schema = tool_info.get("input_schema") or tool_info.get("schema")
        if schema:
            validation_error = self._validate_payload(safe_payload, schema)
            if validation_error:
                raise ToolSafetyError(
                    f"Invalid payload for '{action_type}': {validation_error}",
                    reason="VALIDATION",
                )

        # 4. Get action classification (risk level, approval requirement)
        envelope = self._action_engine.create_action_envelope(action_type, safe_payload)

        # 5. Prepare execution context
        return {
            "action_type": action_type,
            "payload": safe_payload,
            "envelope": envelope,
            "tool_info": tool_info,
            "execution_ready": True,
        }

    def _validate_payload(self, payload: dict[str, Any], schema: dict[str, Any]) -> str | None:
        """Validate payload against JSON schema.

        Args:
            payload: The payload to validate.
            schema: JSON schema dictionary.

        Returns:
            Error message string if invalid, None if valid.
        """
        return validate_input_schema(payload, schema)

    @staticmethod
    def _check_type(value: Any, expected_type: str | None) -> bool:
        """Check if value matches expected JSON schema type."""
        if expected_type is None:
            return True
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "object":
            return isinstance(value, dict)
        return True


class SafeActionExecutor:
    """Executes validated actions through ActionEngine.

    This is the only execution path for tool actions. It ensures:
    - Only validated actions are executed
    - Approval requirements are checked
    - Human intervention is handled
    - Results are normalized
    """

    def __init__(
        self,
        tool_validator: ToolValidator,
        worker_runtime: Any,  # WorkerRuntime for connector dispatch
    ) -> None:
        """Initialize the executor.

        Args:
            tool_validator: The ToolValidator for pre-execution checks.
            worker_runtime: WorkerRuntime for connector actions and approval.
        """
        self._tool_validator = tool_validator
        self._worker_runtime = worker_runtime

    def execute(
        self,
        action_type: str,
        payload: dict[str, Any],
        mission_id: str,
    ) -> dict[str, Any]:
        """Execute a validated action.

        Args:
            action_type: The action type to execute.
            payload: Action payload.
            mission_id: Mission identifier for approval/connector context.

        Returns:
            Execution result dictionary.
        """
        # Validate and prepare
        try:
            prepared = self._tool_validator.validate_and_prepare(action_type, payload)
        except ToolSafetyError as e:
            return {"success": False, "error": str(e), "reason": e.reason}

        envelope = prepared["envelope"]
        safe_payload = prepared["payload"]
        requires_approval = envelope.get("requires_approval", False)
        risk_level = envelope.get("risk_level", "moderate")

        # Handle approval-required actions
        if requires_approval:
            return self._execute_with_approval(
                mission_id=mission_id,
                action_type=action_type,
                payload=safe_payload,
                risk_level=risk_level,
            )

        # Handle connector actions (platform onboarding, etc.)
        if action_type in ("start_platform_onboarding", "resume_platform_onboarding", "connect_platform"):
            return self._worker_runtime.execute_connector_action(
                mission_id=mission_id,
                action_type=action_type,
                payload=safe_payload,
            )

        # Execute safe actions directly through ActionEngine
        return self._tool_validator._action_engine.execute_action(action_type, safe_payload)

    def _execute_with_approval(
        self,
        mission_id: str,
        action_type: str,
        payload: dict[str, Any],
        risk_level: str,
    ) -> dict[str, Any]:
        """Execute action with approval gate."""
        return self._worker_runtime.execute_action_with_approval(
            mission_id=mission_id,
            action_type=action_type,
            payload=payload,
        )

    def continue_after_approval(
        self,
        mission_id: str,
        approval_request_id: str,
        action_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Continue execution after approval is granted."""
        return self._worker_runtime.continue_with_approval(
            mission_id=mission_id,
            approval_request_id=approval_request_id,
            action_type=action_type,
            payload=payload,
        )


def create_tool_validator(
    tool_registry: ToolRegistry,
    action_engine: ActionEngine,
) -> ToolValidator:
    """Factory for creating ToolValidator with standard dependencies."""
    return ToolValidator(tool_registry, action_engine)


def create_safe_action_executor(
    tool_validator: ToolValidator,
    worker_runtime: Any,
) -> SafeActionExecutor:
    """Factory for creating SafeActionExecutor with standard dependencies."""
    return SafeActionExecutor(tool_validator, worker_runtime)