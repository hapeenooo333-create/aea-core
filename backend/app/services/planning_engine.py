"""Planning engine for Sprint 7.2-P1.5.

This module converts user goals into executable plan steps that the employee
loop can execute. The implementation is deterministic and keyphrase-based so
it can run in tests and local environments without LLM dependencies.
"""

from __future__ import annotations

from typing import Any


class PlanningEngine:
    """Convert user goals into executable plan steps.

    The engine parses goal keywords and creates structured plan steps with
    action types, payloads, and expected outcomes. The plan uses the existing
    mission_steps table schema extended via JSONB payload fields.
    """

    # Keyword → (plan_name, action_type, default_payload)
    _KEYWORD_MAP = {
        "echo": (
            "test_echo",
            "test_echo",
            {"message": "test"},
        ),
        "count": (
            "test_count",
            "test_count",
            {"count": 3},
        ),
    }

    def create_plan_from_goal(
        self,
        goal: str,
        mission_id: str,
    ) -> dict[str, Any]:
        """Parse a user goal and create executable plan steps.

        Args:
            goal: The user's natural language goal description.
            mission_id: The mission to attach the plan to.

        Returns:
            Dictionary with plan creation result including generated steps.
        """
        goal_lower = (goal or "").lower().strip()

        # Find matching keyword
        action_type = None
        default_payload = None
        plan_name = None

        for keyword, (pname, ptype, payload) in self._KEYWORD_MAP.items():
            if keyword in goal_lower:
                action_type = ptype
                default_payload = payload
                plan_name = pname
                break

        # Default: log action
        if not action_type:
            action_type = "log"
            default_payload = {"message": goal or "No goal provided"}
            plan_name = "default_log"

        # Create structured plan step(s)
        steps = [
            {
                "step_name": f"{plan_name}_step_1",
                "action_type": action_type,
                "action_payload": dict(default_payload or {}),
                "expected_outcome": self._derive_expected_outcome(action_type, default_payload),
                "status": "pending",
            }
        ]

        return {
            "success": True,
            "plan_name": plan_name,
            "steps": steps,
            "message": f"Plan created with {len(steps)} step(s) for goal: '{goal[:60]}'",
        }

    def _derive_expected_outcome(
        self,
        action_type: str,
        payload: dict[str, Any],
    ) -> str:
        """Derive a human-readable expected outcome from action type and payload."""
        if action_type == "test_echo":
            return f"Message echoed: {payload.get('message', 'unknown')}"
        if action_type == "test_count":
            return f"Counted to {payload.get('count', 0)}"
        return f"Action executed: {action_type}"

    def get_available_actions(self) -> dict[str, dict[str, Any]]:
        """Return available action types and their descriptions."""
        return {
            "test_echo": {
                "description": "Echo a message with metadata",
                "risk_level": "safe",
                "requires_approval": False,
            },
            "test_count": {
                "description": "Count from 1 to N",
                "risk_level": "safe",
                "requires_approval": False,
            },
            "log": {
                "description": "Log a message",
                "risk_level": "safe",
                "requires_approval": False,
            },
        }