"""Employee engine for Sprint 7.2-P1.5.

This module implements the full AI Employee execution loop with human employee
lifecycle management. It coordinates goal → plan → execute → observe → learn →
complete workflow using the existing services.
"""

from __future__ import annotations

from typing import Any

from .action_engine import ActionEngine
from .approval_gateway import ApprovalGateway
from .decision_engine import AtlasDecisionEngine
from .human_intervention import HumanInterventionManager
from .memory_engine import AtlasMemoryEngine
from .mission_engine import MissionEngine
from .planning_engine import PlanningEngine
from .tool_registry import ToolRegistry
from .connectors.registry import ConnectorRegistry


class EmployeeEngine:
    """AI Employee execution loop with complete mission lifecycle.

    The engine manages the full employee experience: loading mission state,
    creating plans from goals, executing steps, handling approvals and human
    intervention, processing observations, and managing completion criteria.
    """

    def __init__(
        self,
        connector_registry: ConnectorRegistry | None = None,
        owner_id: str | None = None,
    ) -> None:
        """Initialize the employee engine with supporting services.

        Args:
            connector_registry: Optional ConnectorRegistry for platform operations.
            owner_id: Canonical owner identifier (auth.users.id).
        """

        self._owner_id = owner_id
        self._mission_engine = MissionEngine()
        self._memory_engine = AtlasMemoryEngine()
        self._decision_engine = AtlasDecisionEngine(owner_id=owner_id)
        self._action_engine = ActionEngine(owner_id=owner_id)
        self._approval_gateway = ApprovalGateway()
        self._planning_engine = PlanningEngine()
        self._tool_registry = ToolRegistry()
        self._connector_registry = connector_registry
        self._human_intervention_manager = HumanInterventionManager()

        # Initialize test tools
        self._initialize_test_tools()

    def _initialize_test_tools(self) -> None:
        """Register test tools for P1-5 minimal vertical slice."""
        # Test tools for deterministic testing
        self._tool_registry.register_tool(
            "test_echo",
            "Echo a message with metadata",
            "internal",
        )
        self._tool_registry.register_tool(
            "test_count",
            "Count from 1 to N",
            "internal",
        )
        self._tool_registry.register_tool(
            "log",
            "Log a message",
            "internal",
        )

    def run_mission(self, mission_id: str) -> dict[str, Any]:
        """Execute a complete mission through the employee loop.

        Args:
            mission_id: The mission identifier to execute.

        Returns:
            Dictionary with execution results including status, progress,
            and any intermediate results.
        """

        mission = self._mission_engine.get_mission(mission_id)
        if not mission:
            return {"success": False, "error": "Mission not found"}

        worker_id = mission.get("assigned_worker") or mission.get("worker_id")
        if not worker_id:
            return {"success": False, "error": "Mission has no assigned worker"}

        # Load mission state (including progress/plans from memory)
        state = self._load_mission_state(mission_id, worker_id)

        # Create plan from goal if no plan exists
        if not state.get("plan_exists"):
            goal = mission.get("title") or mission.get("description") or ""
            plan_result = self._planning_engine.create_plan_from_goal(goal, mission_id)
            if not plan_result.get("success"):
                return plan_result
            state["plan_steps"] = plan_result.get("steps", [])
            state["plan_exists"] = True

        # Select next executable step
        next_step = self._select_next_executable_step(state["plan_steps"])
        if not next_step:
            return self._handle_mission_completion(mission_id, worker_id, state)

        # Execute next step
        execution_result = self._execute_step(mission_id, worker_id, next_step, state)

        # Update mission state
        state = self._update_mission_state(mission_id, worker_id, next_step, execution_result)

        # Check completion criteria
        completion_result = self._check_completion_criteria(mission_id, worker_id, state)
        if completion_result.get("completed"):
            return completion_result

        # Continue loop
        return {
            "success": True,
            "mission_id": mission_id,
            "worker_id": worker_id,
            "current_step": next_step,
            "execution_result": execution_result,
            "progress": self._calculate_progress(state["plan_steps"]),
            "state": state,
            "message": f"Step {next_step.get('step_name')} executed",
        }

    def _load_mission_state(
        self,
        mission_id: str,
        worker_id: str,
    ) -> dict[str, Any]:
        """Load mission state including progress, plan, and memory."""

        state = {
            "mission_id": mission_id,
            "worker_id": worker_id,
            "plan_steps": [],
            "plan_exists": False,
            "memories": [],
            "approval_requests": [],
            "human_interventions": [],
            "recent_memories": [],
        }

        # Load recent memories for context
        memories = self._memory_engine.get_recent_memories(worker_id, limit=5)
        state["memories"] = memories or []
        state["recent_memories"] = memories or []

        # TODO: Load plan steps from mission_steps table or state
        # TODO: Load active approval requests
        # TODO: Load pending human interventions

        return state

    def _select_next_executable_step(
        self,
        plan_steps: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Select the next executable step from plan steps.

        Returns the first step with 'pending' or 'failed' status (for retry).
        """

        for step in plan_steps:
            status = step.get("status", "pending")
            if status in ("pending", "failed"):
                return step

        return None

    def _execute_step(
        self,
        mission_id: str,
        worker_id: str,
        step: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a single plan step through the employee workflow.

        This method handles the complete step execution flow:
        1. Validate tool availability
        2. Handle approval requirements
        3. Execute action
        4. Handle human intervention if needed
        5. Process result

        Returns:
            Execution result dictionary.
        """

        action_type = step.get("action_type")
        payload = step.get("action_payload", {})

        # Add worker_id to payload for memory tracking
        payload["worker_id"] = worker_id

        # Validate tool is registered
        tool_check = self._tool_registry.is_available(action_type)
        if not tool_check.get("available"):
            return {"success": False, "error": f"Tool not available: {action_type}"}

        # Get action classification
        envelope = self._action_engine.create_action_envelope(action_type, payload)

        # Handle approval if required
        if envelope.get("requires_approval"):
            approval_result = self._handle_approval_for_step(
                mission_id, action_type, payload, envelope, step
            )
            if not approval_result.get("success"):
                return approval_result

        # Execute the action
        execution_result = self._action_engine.execute_action(action_type, payload)

        # Handle connector actions that may require human intervention
        if action_type in ("start_platform_onboarding", "connect_platform"):
            connector_result = self._handle_connector_action(
                mission_id, action_type, payload
            )
            if connector_result.get("awaiting_human_intervention"):
                return connector_result

        return execution_result

    def _handle_approval_for_step(
        self,
        mission_id: str,
        action_type: str,
        payload: dict[str, Any],
        envelope: dict[str, Any],
        step: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle approval request creation and pending state for sensitive actions.

        Returns approval result or pending approval status.
        """

        request_result = self._approval_gateway.create_request(
            mission_id=mission_id,
            action_type=action_type,
            risk_level=envelope.get("risk_level", "moderate"),
            payload=payload,
        )

        if not request_result.get("success"):
            return request_result

        request = request_result.get("request", {})
        return {
            "success": False,
            "pending_approval": True,
            "approval_request_id": request.get("id"),
            "action_type": action_type,
            "message": f"Action {action_type} requires approval",
        }

    def _handle_connector_action(
        self,
        mission_id: str,
        action_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle connector actions with human intervention support."""

        if not self._connector_registry:
            return {"success": False, "error": "Connector registry not available"}

        platform = payload.get("platform")
        if not platform:
            return {"success": False, "error": "Platform must be specified"}

        connector = self._connector_registry.get(platform)
        if not connector:
            return {"success": False, "error": f"Connector not found for {platform}"}

        # Dispatch to connector
        result = self._dispatch_to_connector(
            mission_id, action_type, payload, connector
        )

        return result

    def _dispatch_to_connector(
        self,
        mission_id: str,
        action_type: str,
        payload: dict[str, Any],
        connector: Any,
    ) -> dict[str, Any]:
        """Dispatch action to connector and handle results including human intervention."""

        worker_id = payload.get("worker_id")

        try:
            if action_type == "start_platform_onboarding":
                result = connector.start_onboarding(worker_id, mission_id=mission_id)

                if result.get("requires_human_intervention"):
                    checkpoint_result = self._human_intervention_manager.create_checkpoint(
                        mission_id=mission_id,
                        platform=connector.platform,
                        checkpoint_type=result.get("checkpoint_type", "manual_platform_step_required"),
                        instructions=result.get("instructions", "Complete the required step"),
                        metadata={
                            "workflow_id": result.get("workflow_id"),
                            "step": result.get("current_step"),
                            "total_steps": result.get("total_steps"),
                        },
                    )

                    if checkpoint_result.get("success"):
                        checkpoint = checkpoint_result.get("checkpoint", {})
                        return {
                            "success": False,
                            "awaiting_human_intervention": True,
                            "checkpoint_id": checkpoint.get("id"),
                            "action_type": action_type,
                            "platform": connector.platform,
                            "workflow_id": result.get("workflow_id"),
                            "instructions": result.get("instructions"),
                            "message": f"Human intervention required: {result.get('instructions')}",
                        }

                return result

            elif action_type == "connect_platform":
                result = connector.connect_platform(worker_id, mission_id=mission_id)
                return result

        except NotImplementedError:
            return {"success": False, "error": f"Action {action_type} not supported for {connector.platform}"}
        except Exception as e:
            return {"success": False, "error": f"Connector error: {str(e)}"}

    def _update_mission_state(
        self,
        mission_id: str,
        worker_id: str,
        step: dict[str, Any],
        execution_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Update mission state after step execution."""

        state = self._load_mission_state(mission_id, worker_id)

        # Update step status based on execution result
        step_name = step.get("step_name")
        for plan_step in state.get("plan_steps", []):
            if plan_step.get("step_name") == step_name:
                if execution_result.get("success"):
                    plan_step["status"] = "completed"
                    plan_step["actual_outcome"] = execution_result.get("result")
                else:
                    plan_step["status"] = "failed"
                    plan_step["error"] = execution_result.get("error")
                break

        return state

    def _handle_mission_completion(
        self,
        mission_id: str,
        worker_id: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle mission completion when no more executable steps remain."""

        # Check if all steps succeeded
        all_completed = all(
            step.get("status") == "completed" for step in state.get("plan_steps", [])
        )

        if all_completed:
            # Complete mission
            result = self._mission_engine.complete_mission(
                mission_id,
                {"plan": state.get("plan_steps"), "memories": state.get("memories")},
            )
            return {
                "success": True,
                "mission_id": mission_id,
                "worker_id": worker_id,
                "completed": True,
                "plan": state.get("plan_steps"),
                "message": "Mission completed successfully",
            }

        return {
            "success": False,
            "mission_id": mission_id,
            "worker_id": worker_id,
            "completed": False,
            "error": "No executable steps remaining but not all steps completed",
        }

    def _check_completion_criteria(
        self,
        mission_id: str,
        worker_id: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Check if mission completion criteria are met."""

        mission = self._mission_engine.get_mission(mission_id)
        if not mission:
            return {"completed": False, "error": "Mission not found"}

        # Check if mission status is already completed
        if mission.get("status") == "completed":
            return {"completed": True, "mission_id": mission_id}

        # Check if all plan steps completed
        plan_steps = state.get("plan_steps", [])
        if not plan_steps:
            return {"completed": False}

        all_completed = all(step.get("status") == "completed" for step in plan_steps)

        return {
            "completed": all_completed,
            "mission_id": mission_id,
            "worker_id": worker_id,
            "plan_steps_count": len(plan_steps),
            "completed_steps_count": sum(
                1 for step in plan_steps if step.get("status") == "completed"
            ),
        }

    def _calculate_progress(
        self,
        plan_steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Calculate mission progress metrics."""

        total = len(plan_steps)
        if total == 0:
            return {"completed": 0, "total": 0, "percentage": 0.0}

        completed = sum(1 for step in plan_steps if step.get("status") == "completed")
        return {
            "completed": completed,
            "total": total,
            "percentage": round((completed / total) * 100, 1),
        }