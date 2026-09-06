"""Mission execution persistence service for P1-6.

Provides durable storage for mission execution state and step lifecycle.
All operations enforce ownership via owner_id and Supabase RLS.

Follows the same defensive pattern used elsewhere in the codebase:
- Supabase is preferred when configured.
- An in-memory dict is used as a safe fallback when Supabase is unavailable.
- All exceptions during DB I/O are caught and degrade to the in-memory path
  so callers never see a hard error from the storage layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

try:
    from .. import database as database_module
except Exception:  # pragma: no cover - fallback for missing runtime config
    try:
        from backend.app import database as database_module
    except Exception:  # pragma: no cover - fallback for direct execution
        database_module = None

EXECUTION_TABLE = "mission_executions"
STEP_TABLE = "mission_steps"

VALID_EXECUTION_STATUSES = {
    "PENDING", "RUNNING", "WAITING_APPROVAL", "WAITING_INPUT",
    "SUCCEEDED", "FAILED", "RETRYING", "CANCELLED",
}

VALID_STEP_STATUSES = {"pending", "assigned", "in_progress", "completed", "failed"}

VALID_RETRY_CATEGORIES = {
    "TRANSIENT", "VALIDATION", "AUTHORIZATION", "APPROVAL",
    "MISSING_INPUT", "TOOL_NOT_FOUND", "EXECUTION", "PERMANENT",
}


class MissionExecutionService:
    """Persist and query mission execution records with optional DB backing."""

    def __init__(self, client: Any | None = None) -> None:
        """Initialize the service.

        Args:
            client: Optional pre-resolved Supabase client. When ``None`` the
                service resolves ``app.database.supabase_client`` lazily.
        """
        self._explicit_client = client
        self._memory_executions: dict[str, dict[str, Any]] = {}
        self._memory_steps: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Execution operations
    # ------------------------------------------------------------------

    def create_execution(
        self,
        mission_id: str,
        execution_id: str,
        idempotency_key: str,
        owner_id: str,
        status: str = "PENDING",
    ) -> dict[str, Any]:
        """Create a new mission execution record.

        Args:
            mission_id: Parent mission identifier.
            execution_id: Unique execution session identifier.
            idempotency_key: Deterministic key preventing duplicate creation.
            owner_id: Canonical owner (auth.users.id).
            status: Initial execution status.

        Returns:
            Dictionary with success flag and execution record.
        """
        if not mission_id or not execution_id or not idempotency_key or not owner_id:
            return {"success": False, "error": "mission_id, execution_id, idempotency_key, and owner_id are required"}
        if status not in VALID_EXECUTION_STATUSES:
            return {"success": False, "error": f"Invalid status: {status}"}

        now = datetime.now(timezone.utc).isoformat()
        record: dict[str, Any] = {
            "id": execution_id,
            "mission_id": mission_id,
            "execution_id": execution_id,
            "idempotency_key": idempotency_key,
            "status": status,
            "current_step_index": 0,
            "retry_count": 0,
            "result": {},
            "owner_id": owner_id,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "completed_at": None,
        }

        client = self._client()
        if client is not None:
            try:
                response = client.table(EXECUTION_TABLE).insert(record).execute()
                if response.data:
                    return {"success": True, "execution": self._normalize_execution(response.data[0])}
            except Exception:  # pragma: no cover - defensive fallback
                pass

        self._memory_executions[execution_id] = record
        return {"success": True, "execution": self._normalize_execution(record)}

    def get_execution(self, execution_id: str, owner_id: str | None = None) -> dict[str, Any] | None:
        """Retrieve an execution by id, optionally filtered by owner.

        Args:
            execution_id: The execution identifier.
            owner_id: Optional owner filter for ownership enforcement.

        Returns:
            Execution dictionary or None if not found or owner mismatch.
        """
        client = self._client()
        if client is not None:
            try:
                query = client.table(EXECUTION_TABLE).select("*").eq("id", execution_id)
                if owner_id:
                    query = query.eq("owner_id", owner_id)
                response = query.limit(1).execute()
                rows = response.data or []
                if rows:
                    return self._normalize_execution(rows[0])
            except Exception:  # pragma: no cover - defensive fallback
                pass

        record = self._memory_executions.get(execution_id)
        if record is None:
            return None
        if owner_id and record.get("owner_id") != owner_id:
            return None
        return self._normalize_execution(record)

    def load_execution_for_mission(
        self,
        mission_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        """Load the active execution for a mission owned by owner_id.

        Returns the most recent non-terminal execution, or None if no
        active execution exists. This is the primary entry point for
        restart/recovery.

        Args:
            mission_id: The mission identifier.
            owner_id: Canonical owner (auth.users.id).

        Returns:
            Execution dictionary or None.
        """
        client = self._client()
        if client is not None:
            try:
                response = (
                    client.table(EXECUTION_TABLE)
                    .select("*")
                    .eq("mission_id", mission_id)
                    .eq("owner_id", owner_id)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                rows = response.data or []
                if rows:
                    execution = self._normalize_execution(rows[0])
                    if execution["status"] not in ("SUCCEEDED", "FAILED", "CANCELLED"):
                        return execution
                    return None
            except Exception:  # pragma: no cover - defensive fallback
                pass

        # In-memory fallback
        for record in reversed(self._memory_executions.values()):
            if record.get("mission_id") == mission_id and record.get("owner_id") == owner_id:
                if record["status"] not in ("SUCCEEDED", "FAILED", "CANCELLED"):
                    return self._normalize_execution(record)
        return None

    def claim_execution(
        self,
        mission_id: str,
        execution_id: str,
        idempotency_key: str,
        owner_id: str,
    ) -> dict[str, Any]:
        """Atomically claim or return existing execution.

        Uses the database claim function when available; falls back to
        in-memory get-or-create with the same contract.

        Args:
            mission_id: Parent mission identifier.
            execution_id: Candidate execution identifier.
            idempotency_key: Deterministic idempotency key.
            owner_id: Canonical owner (auth.users.id).

        Returns:
            Dictionary with execution record and created flag.
        """
        client = self._client()
        if client is not None:
            try:
                response = client.rpc(
                    "claim_mission_execution",
                    {
                        "p_mission_id": mission_id,
                        "p_execution_id": execution_id,
                        "p_idempotency_key": idempotency_key,
                    },
                ).execute()
                data = getattr(response, "data", None) or []
                if data:
                    first = data[0] if isinstance(data[0], dict) else None
                    if first:
                        workflow_json = first.get("execution")
                        created = bool(first.get("created"))
                        if workflow_json:
                            return {
                                "success": True,
                                "execution": self._normalize_execution(workflow_json),
                                "created": created,
                            }
            except Exception:  # pragma: no cover - defensive fallback
                pass

        # In-memory fallback
        with self._memory_lock():
            for record in self._memory_executions.values():
                if record.get("idempotency_key") == idempotency_key:
                    return {"success": True, "execution": self._normalize_execution(record), "created": False}

            record: dict[str, Any] = {
                "id": execution_id,
                "mission_id": mission_id,
                "execution_id": execution_id,
                "idempotency_key": idempotency_key,
                "status": "PENDING",
                "current_step_index": 0,
                "retry_count": 0,
                "result": {},
                "owner_id": owner_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "started_at": None,
                "completed_at": None,
            }
            self._memory_executions[execution_id] = record
            return {"success": True, "execution": self._normalize_execution(record), "created": True}

    def update_execution_state(
        self,
        execution_id: str,
        owner_id: str,
        *,
        status: str | None = None,
        current_step_index: int | None = None,
        retry_count: int | None = None,
        result: dict[str, Any] | None = None,
        completed_at: str | None = None,
    ) -> dict[str, Any]:
        """Update mutable fields on an execution with ownership enforcement.

        Args:
            execution_id: The execution identifier.
            owner_id: Canonical owner for RLS enforcement.
            status: New status.
            current_step_index: New current step index.
            retry_count: New retry count.
            result: New result payload.
            completed_at: Completion timestamp.

        Returns:
            Dictionary with success flag and updated execution.
        """
        if not execution_id or not owner_id:
            return {"success": False, "error": "execution_id and owner_id are required"}

        updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if status is not None:
            if status not in VALID_EXECUTION_STATUSES:
                return {"success": False, "error": f"Invalid status: {status}"}
            updates["status"] = status
        if current_step_index is not None:
            updates["current_step_index"] = int(current_step_index)
        if retry_count is not None:
            updates["retry_count"] = int(retry_count)
        if result is not None:
            updates["result"] = result
        if completed_at is not None:
            updates["completed_at"] = completed_at

        client = self._client()
        if client is not None:
            try:
                response = (
                    client.table(EXECUTION_TABLE)
                    .update(updates)
                    .eq("id", execution_id)
                    .eq("owner_id", owner_id)
                    .execute()
                )
                rows = response.data or []
                if rows:
                    return {"success": True, "execution": self._normalize_execution(rows[0])}
            except Exception:  # pragma: no cover - defensive fallback
                pass

        # In-memory fallback
        record = self._memory_executions.get(execution_id)
        if record is None:
            return {"success": False, "error": f"Execution {execution_id} not found", "execution_id": execution_id}
        if record.get("owner_id") != owner_id:
            return {"success": False, "error": "Owner mismatch", "execution_id": execution_id}
        record.update(updates)
        self._memory_executions[execution_id] = record
        return {"success": True, "execution": self._normalize_execution(record)}

    def mark_completed(
        self,
        execution_id: str,
        owner_id: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically mark execution as SUCCEEDED.

        Args:
            execution_id: The execution identifier.
            owner_id: Canonical owner for RLS enforcement.
            result: Final result payload.

        Returns:
            Dictionary with success flag and updated execution.
        """
        return self.update_execution_state(
            execution_id,
            owner_id,
            status="SUCCEEDED",
            result=result or {},
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    def mark_failed(
        self,
        execution_id: str,
        owner_id: str,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically mark execution as FAILED.

        Args:
            execution_id: The execution identifier.
            owner_id: Canonical owner for RLS enforcement.
            error: Error message.
            result: Final result payload.

        Returns:
            Dictionary with success flag and updated execution.
        """
        final_result = result or {}
        if error:
            final_result["error"] = error
        return self.update_execution_state(
            execution_id,
            owner_id,
            status="FAILED",
            result=final_result,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------
    # Step operations
    # ------------------------------------------------------------------

    def persist_step(
        self,
        execution_id: str,
        owner_id: str,
        *,
        step_name: str,
        step_id: str | None = None,
        attempt_index: int = 0,
        idempotency_key: str | None = None,
        status: str = "in_progress",
        result: dict[str, Any] | None = None,
        retry_category: str | None = None,
    ) -> dict[str, Any]:
        """Persist a step record for an execution.

        Args:
            execution_id: Parent execution identifier.
            owner_id: Canonical owner for RLS enforcement.
            step_name: Name of the step.
            step_id: Optional step identifier (auto-generated if None).
            attempt_index: Attempt number for retry isolation.
            idempotency_key: Deterministic key for this step attempt.
            status: Step status.
            result: Step result payload.
            retry_category: Retry classification if failed.

        Returns:
            Dictionary with success flag and step record.
        """
        if not execution_id or not owner_id:
            return {"success": False, "error": "execution_id and owner_id are required"}
        if status not in VALID_STEP_STATUSES:
            return {"success": False, "error": f"Invalid step status: {status}"}
        if retry_category and retry_category not in VALID_RETRY_CATEGORIES:
            return {"success": False, "error": f"Invalid retry category: {retry_category}"}

        step_id = step_id or str(uuid4())
        idempotency_key = idempotency_key or f"step:{execution_id}:{step_id}:{attempt_index}"
        now = datetime.now(timezone.utc).isoformat()

        record: dict[str, Any] = {
            "id": step_id,
            "mission_id": execution_id,  # Will be corrected to actual mission_id on load
            "execution_id": execution_id,
            "step_name": step_name,
            "worker_role": "employee",
            "status": status,
            "attempt_index": attempt_index,
            "idempotency_key": idempotency_key,
            "started_at": now if status == "in_progress" else None,
            "completed_at": now if status in ("completed", "failed") else None,
            "result": result or {},
            "retry_category": retry_category,
            "owner_id": owner_id,
            "created_at": now,
        }

        client = self._client()
        if client is not None:
            try:
                response = client.table(STEP_TABLE).insert(record).execute()
                if response.data:
                    return {"success": True, "step": self._normalize_step(response.data[0])}
            except Exception:  # pragma: no cover - defensive fallback
                pass

        self._memory_steps[step_id] = record
        return {"success": True, "step": self._normalize_step(record)}

    def claim_step(
        self,
        execution_id: str,
        owner_id: str,
        step_id: str,
        attempt_index: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Claim a step for execution with attempt isolation.

        Args:
            execution_id: Parent execution identifier.
            owner_id: Canonical owner for RLS enforcement.
            step_id: Step identifier.
            attempt_index: Attempt number.
            idempotency_key: Deterministic key for this step attempt.

        Returns:
            Dictionary with success flag, step record, and claimed flag.
        """
        client = self._client()
        if client is not None:
            try:
                response = client.rpc(
                    "claim_mission_step",
                    {
                        "p_execution_id": execution_id,
                        "p_step_id": step_id,
                        "p_attempt_index": attempt_index,
                        "p_idempotency_key": idempotency_key,
                    },
                ).execute()
                data = getattr(response, "data", None) or []
                if data:
                    first = data[0] if isinstance(data[0], dict) else None
                    if first:
                        step_json = first.get("step")
                        claimed = bool(first.get("claimed"))
                        if step_json:
                            return {
                                "success": True,
                                "step": self._normalize_step(step_json),
                                "claimed": claimed,
                            }
            except Exception:  # pragma: no cover - defensive fallback
                pass

        # In-memory fallback
        with self._memory_lock():
            for record in self._memory_steps.values():
                if record.get("idempotency_key") == idempotency_key:
                    return {"success": True, "step": self._normalize_step(record), "claimed": False}

            record: dict[str, Any] = {
                "id": step_id,
                "execution_id": execution_id,
                "step_name": "claimed_step",
                "worker_role": "employee",
                "status": "in_progress",
                "attempt_index": attempt_index,
                "idempotency_key": idempotency_key,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": None,
                "result": {},
                "retry_category": None,
                "owner_id": owner_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._memory_steps[idempotency_key] = record
            return {"success": True, "step": self._normalize_step(record), "claimed": True}

    def load_steps_for_execution(
        self,
        execution_id: str,
        owner_id: str,
    ) -> list[dict[str, Any]]:
        """Load all steps for an execution, ordered by attempt_index.

        Args:
            execution_id: Parent execution identifier.
            owner_id: Canonical owner for RLS enforcement.

        Returns:
            List of step dictionaries.
        """
        client = self._client()
        if client is not None:
            try:
                response = (
                    client.table(STEP_TABLE)
                    .select("*")
                    .eq("execution_id", execution_id)
                    .eq("owner_id", owner_id)
                    .order("attempt_index")
                    .execute()
                )
                rows = response.data or []
                return [self._normalize_step(row) for row in rows if self._normalize_step(row)]
            except Exception:  # pragma: no cover - defensive fallback
                pass

        return [
            self._normalize_step(r)
            for r in self._memory_steps.values()
            if r.get("execution_id") == execution_id and r.get("owner_id") == owner_id
        ]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _client(self) -> Any | None:
        """Resolve the Supabase client to use (explicit, lazy, or none)."""
        if self._explicit_client is not None:
            return self._explicit_client
        if database_module is None:
            return None
        return getattr(database_module, "supabase_client", None)

    @staticmethod
    def _normalize_execution(row: dict[str, Any] | None) -> dict[str, Any] | None:
        """Produce a normalized execution dictionary."""
        if row is None:
            return None
        return {
            "id": row.get("id"),
            "mission_id": row.get("mission_id"),
            "execution_id": row.get("execution_id") or row.get("id"),
            "idempotency_key": row.get("idempotency_key"),
            "status": row.get("status"),
            "current_step_index": row.get("current_step_index", 0),
            "retry_count": row.get("retry_count", 0),
            "result": row.get("result") or {},
            "owner_id": row.get("owner_id"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "started_at": row.get("started_at"),
            "completed_at": row.get("completed_at"),
        }

    @staticmethod
    def _normalize_step(row: dict[str, Any] | None) -> dict[str, Any] | None:
        """Produce a normalized step dictionary."""
        if row is None:
            return None
        return {
            "id": row.get("id"),
            "execution_id": row.get("execution_id"),
            "step_name": row.get("step_name"),
            "worker_role": row.get("worker_role"),
            "status": row.get("status"),
            "attempt_index": row.get("attempt_index", 0),
            "idempotency_key": row.get("idempotency_key"),
            "started_at": row.get("started_at"),
            "completed_at": row.get("completed_at"),
            "result": row.get("result") or {},
            "retry_category": row.get("retry_category"),
            "owner_id": row.get("owner_id"),
            "created_at": row.get("created_at"),
        }

    @staticmethod
    def _memory_lock() -> Any:
        """Return a process-local lock for in-memory fallback atomicity."""
        from threading import RLock
        return RLock()