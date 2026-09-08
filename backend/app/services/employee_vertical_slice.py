"""P1-7B objective-to-report employee vertical slice.

This module composes the existing P1-4/P1-6/P1-7A services. It owns no
alternative persistence or authorization model: execution state goes through
MissionExecutionService and external side effects go through ApprovalGateway.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .approval_gateway import ApprovalGateway
from .approval_resume_service import ApprovalResumeService
from .capability_discovery import CapabilityDiscovery
from .connectors.pinterest_connector import PinterestConnector
from .connectors.registry import ConnectorRegistry
from .memory_engine import AtlasMemoryEngine
from .mission_execution_service import MissionExecutionService
from .p1_7_contracts import (
    BoundedDecisionLoop,
    ObjectiveParser,
    Observation,
    ToolContract,
    sanitize_payload,
)
from .plan_validator import PlanValidator
from .retry_classifier import classify_failure
from .stores.platform_connection_store import PlatformConnectionStore
from .stores.onboarding_workflow_store import OnboardingWorkflowStore
from .tool_registry import ToolRegistry
from .tool_safety import ToolSafetyError, ToolValidator
from .action_engine import ActionEngine


class EmployeeVerticalSlice:
    """Run one bounded, user-scoped employee objective."""

    def __init__(
        self,
        owner_id: str,
        *,
        connector_registry: ConnectorRegistry | None = None,
        client: Any | None = None,
        connection_store: PlatformConnectionStore | None = None,
        execution_service: MissionExecutionService | None = None,
        approval_gateway: ApprovalGateway | None = None,
        memory_engine: AtlasMemoryEngine | None = None,
        max_decisions: int = 3,
    ) -> None:
        if not owner_id:
            raise ValueError("owner_id is required")
        self.owner_id = owner_id
        self._client = client
        self._connectors = connector_registry or ConnectorRegistry()
        if not self._connectors.has_connector("pinterest"):
            self._connectors.register(PinterestConnector(
                workflow_store=OnboardingWorkflowStore(client=client),
                connection_store=PlatformConnectionStore(client=client),
            ))
        self._connections = connection_store or PlatformConnectionStore(client=client)
        self._execution = execution_service or MissionExecutionService(client=client)
        self._approvals = approval_gateway or ApprovalGateway(client=client)
        self._memory = memory_engine or AtlasMemoryEngine(client=client, owner_id=owner_id)
        self._tools = ToolRegistry()
        self._register_tools()
        self._discovery = CapabilityDiscovery(self._tools, self._connectors)
        self._validator = PlanValidator(self._tools, self._discovery)
        self._tool_validator = ToolValidator(self._tools, ActionEngine(owner_id=owner_id))
        self._max_decisions = max_decisions

    def _register_tools(self) -> None:
        self._tools.register_contract(ToolContract(
            tool_name="log",
            description="Record a non-sensitive employee outcome",
            input_schema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
                "additionalProperties": False,
            },
            risk_level="READ_ONLY",
        ))
        self._tools.register_contract(ToolContract(
            tool_name="pinterest.get_account_status",
            description="Read the authenticated user's Pinterest connection status",
            input_schema={
                "type": "object",
                "properties": {"platform": {"type": "string"}},
                "required": ["platform"],
                "additionalProperties": False,
            },
            capability="account_status",
            platform="pinterest",
            operation="get_account_status",
            risk_level="READ_ONLY",
        ))
        self._tools.register_contract(ToolContract(
            tool_name="start_platform_onboarding",
            description="Start Pinterest onboarding after user approval",
            input_schema={
                "type": "object",
                "properties": {"platform": {"type": "string"}},
                "required": ["platform"],
                "additionalProperties": False,
            },
            capability="onboarding",
            platform="pinterest",
            operation="start_onboarding",
            risk_level="WRITE_EXTERNAL",
            requires_approval=True,
            idempotency_behavior="approval_and_workflow_idempotent",
        ))

    def discover_capabilities(self) -> dict[str, Any]:
        """Return only tools available to this owner and their connections."""
        return self._discovery.discover(
            self.owner_id,
            lambda owner, platform: self._connections.get(owner, platform),
        )

    def run(
        self,
        goal: str,
        *,
        mission_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Understand, plan, validate, execute, observe, and report."""
        mission_id = mission_id or f"p1-7b-{uuid4()}"
        objective = ObjectiveParser().parse(goal, metadata)
        discovered = self.discover_capabilities()
        plan = self._build_plan(objective, discovered)
        validation = self._validator.validate(
            plan,
            owner_id=self.owner_id,
            discovered=discovered,
        )
        report: dict[str, Any] = {
            "user_goal": objective.goal,
            "understood_objective": objective.to_dict(),
            "discovered_capabilities": discovered,
            "plan": plan,
            "selected_tools": [step.get("tool_name") for step in plan],
            "approvals": [],
            "executed_actions": [],
            "results": [],
            "failures_retries": [],
            "learning": [],
            "required_user_action": None,
            "resume_information": None,
        }
        if not validation.get("success"):
            report.update({"final_status": "FAIL", "failures_retries": validation["errors"]})
            return {"success": False, "status": "FAIL", "report": sanitize_payload(report)}

        execution_id = str(uuid4())
        claim = self._execution.claim_execution(
            mission_id, execution_id, f"p1-7b:{self.owner_id}:{mission_id}", self.owner_id,
        )
        if not claim.get("success"):
            return self._failed_report(report, claim.get("error", "Execution claim failed"))
        execution = claim["execution"]
        execution_id = execution["execution_id"]
        if execution.get("status") in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            report["final_status"] = execution["status"]
            report["execution_id"] = execution_id
            return {"success": execution["status"] == "SUCCEEDED", "status": execution["status"], "report": sanitize_payload(report)}

        self._execution.update_execution_state(execution_id, self.owner_id, status="RUNNING")
        step = plan[0]
        step_name = step.get("step_name", "p1_7b_step_1")
        self._execution.persist_step(
            execution_id, self.owner_id, step_name=step_name,
            step_id=str(uuid4()), attempt_index=0,
            idempotency_key=f"p1-7b:{execution_id}:{step_name}:0", status="in_progress",
        )
        result = self._execute_tool(step, mission_id, execution_id)
        report["execution_id"] = execution_id
        report["executed_actions"].append(sanitize_payload(step))
        report["results"].append(sanitize_payload(result))
        report["approvals"] = self._approval_summary(result)
        observation = Observation(
            action=step["tool_name"], result=result, success=bool(result.get("success")),
            state_change="completed" if result.get("success") else "paused_or_failed",
            new_information=[str(result.get("status"))] if result.get("status") else [],
            next_possible_actions=["COMPLETE", "WAIT_FOR_APPROVAL", "WAIT_FOR_HUMAN_INPUT", "RETRY", "FAIL"],
        )
        report["observation"] = observation.to_dict()
        decision = self._next_decision(result)
        report["decision"] = decision
        report["learning"] = ["Pinterest account status was checked without persisting credentials"] if step["tool_name"] == "pinterest.get_account_status" else []

        step_status = "completed" if result.get("success") else "failed"
        retry_category = None if result.get("success") else classify_failure(result.get("error", "execution failure")).category
        self._execution.persist_step(
            execution_id, self.owner_id, step_name=step_name,
            attempt_index=0, idempotency_key=f"p1-7b:{execution_id}:{step_name}:0",
            status=step_status, result=sanitize_payload(result), retry_category=retry_category,
        )
        if decision == "COMPLETE":
            self._execution.mark_completed(execution_id, self.owner_id, {"report": sanitize_payload(report)})
        elif decision == "WAIT_FOR_APPROVAL":
            self._execution.update_execution_state(execution_id, self.owner_id, status="WAITING_APPROVAL", result=sanitize_payload(result))
            report["required_user_action"] = "Approve the pending action"
            report["resume_information"] = {"approval_request_id": result.get("approval_request_id"), "execution_id": execution_id}
        elif decision == "WAIT_FOR_HUMAN_INPUT":
            self._execution.update_execution_state(execution_id, self.owner_id, status="WAITING_INPUT", result=sanitize_payload(result))
            report["required_user_action"] = result.get("message", "Complete the requested human step")
        else:
            self._execution.mark_failed(execution_id, self.owner_id, result=result)
        report["final_status"] = decision
        return {"success": decision == "COMPLETE", "status": decision, "report": sanitize_payload(report)}

    def resume_approval(self, approval_request_id: str) -> dict[str, Any]:
        """Resume an approved onboarding action through ApprovalResumeService."""
        request = self._approvals.get_request(approval_request_id)
        request_payload = request.get("payload") or {} if request else {}
        if not request or request_payload.get("worker_id") != self.owner_id:
            return {"success": False, "status": "FAIL", "error": "Approval request not found"}
        resume_service = ApprovalResumeService(
            approval_gateway=self._approvals,
            connector_registry=self._connectors,
        )
        result = resume_service.resume(approval_request_id)
        safe_result = sanitize_payload(result)
        payload = request.get("payload") or {}
        execution_id = payload.get("execution_id")
        if execution_id:
            if result.get("status") == "completed":
                self._execution.mark_completed(execution_id, self.owner_id, {"approval_resume": safe_result})
            elif result.get("status") == "awaiting_human_intervention":
                self._execution.update_execution_state(execution_id, self.owner_id, status="WAITING_INPUT", result=safe_result)
        return {"success": result.get("status") in {"completed", "resumed"}, "status": result.get("status"), "result": safe_result}

    def _build_plan(self, objective: Any, discovered: dict[str, Any]) -> list[dict[str, Any]]:
        goal = objective.goal.lower()
        platform = "pinterest" if "pinterest" in goal or "board" in goal else None
        if platform and any(word in goal for word in ("connect", "onboard", "authorize")):
            tool_name = "start_platform_onboarding"
        elif platform and any(word in goal for word in ("status", "account", "board", "connection", "list")):
            tool_name = "pinterest.get_account_status"
        else:
            tool_name = "log"
        payload = {"platform": platform} if platform else {"message": objective.goal or "No goal provided"}
        return [{"step_name": "p1_7b_step_1", "tool_name": tool_name, "input": payload, "action_type": tool_name, "action_payload": payload}]

    def _execute_tool(self, step: dict[str, Any], mission_id: str, execution_id: str) -> dict[str, Any]:
        tool_name = step["tool_name"]
        payload = dict(step.get("input") or {})
        try:
            prepared = self._tool_validator.validate_and_prepare(tool_name, payload)
        except ToolSafetyError as exc:
            return {"success": False, "error": str(exc), "reason": exc.reason}
        if tool_name == "pinterest.get_account_status":
            connector = self._connectors.get("pinterest")
            if connector is None:
                return {"success": False, "status": "UNAVAILABLE", "error": "Pinterest connector is unavailable"}
            return connector.get_account_status(self.owner_id)
        if tool_name == "start_platform_onboarding":
            request = self._approvals.create_request(
                mission_id=mission_id, action_type="start_platform_onboarding",
                risk_level="WRITE_EXTERNAL",
                payload={**prepared["payload"], "worker_id": self.owner_id, "execution_id": execution_id},
                owner_id=self.owner_id,
            )
            if not request.get("success"):
                return request
            return {"success": False, "pending_approval": True, "status": "WAITING_APPROVAL", "approval_request_id": request["request"].get("id"), "message": "Approval required before Pinterest onboarding"}
        return ActionEngine(owner_id=self.owner_id).execute_action(tool_name, prepared["payload"])

    def _next_decision(self, result: dict[str, Any]) -> str:
        loop = BoundedDecisionLoop(self._max_decisions)
        if not loop.allow_next():
            return "FAIL"
        if result.get("pending_approval"):
            return "WAIT_FOR_APPROVAL"
        if result.get("awaiting_human_intervention") or result.get("waiting_input"):
            return "WAIT_FOR_HUMAN_INPUT"
        if result.get("success"):
            return "COMPLETE"
        if classify_failure(result.get("error", "execution failure")).retryable and loop.allow_next():
            return "RETRY"
        return "FAIL"

    @staticmethod
    def _approval_summary(result: dict[str, Any]) -> list[dict[str, Any]]:
        if not result.get("approval_request_id"):
            return []
        return [{"approval_request_id": result["approval_request_id"], "status": result.get("status", "pending")}]

    @staticmethod
    def _failed_report(report: dict[str, Any], error: str) -> dict[str, Any]:
        report["final_status"] = "FAIL"
        report["failures_retries"] = [error]
        return {"success": False, "status": "FAIL", "report": sanitize_payload(report)}


__all__ = ["EmployeeVerticalSlice"]
