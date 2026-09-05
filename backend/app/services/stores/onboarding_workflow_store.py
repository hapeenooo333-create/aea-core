"""Onboarding workflow persistence store.

Backed by ``public.onboarding_workflows`` (see
``database/migrations/sprint7_2b_platform_connectors.sql``).

The store follows the same defensive pattern used elsewhere in the codebase:
- Supabase is preferred when configured.
- An in-memory dict is used as a safe fallback when Supabase is unavailable.
- All exceptions during DB I/O are caught and degrade to the in-memory path
  so callers never see a hard error from the storage layer.

The store never persists OAuth secrets, tokens, or authorization codes.
``checkpoint_data`` and ``step_history`` are stored as JSONB and are
expected to carry non-sensitive context only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

try:
    from .. import database as database_module
except Exception:  # pragma: no cover - defensive import fallback
    try:
        from backend.app import database as database_module
    except Exception:  # pragma: no cover - defensive import fallback
        database_module = None


TABLE_NAME = "onboarding_workflows"


class OnboardingWorkflowStore:
    """Persist onboarding workflow records with optional DB backing."""

    def __init__(self, client: Any | None = None) -> None:
        """Initialize the store.

        Args:
            client: Optional pre-resolved Supabase client. When ``None`` the
                store resolves ``app.database.supabase_client`` lazily.
        """
        self._explicit_client = client
        self._memory_store: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def create(
        self,
        workflow_id: str,
        mission_id: str | None,
        worker_id: str,
        platform: str,
        status: str,
        current_step: int,
        total_steps: int,
        checkpoint_data: dict[str, Any] | None,
        step_history: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Create a new onboarding workflow record.

        Returns:
            A normalized workflow dictionary.
        """
        if not workflow_id:
            return {"success": False, "error": "workflow_id is required"}
        if not worker_id:
            return {"success": False, "error": "worker_id is required"}
        if not platform:
            return {"success": False, "error": "platform is required"}

        now = datetime.now(timezone.utc).isoformat()
        safe_checkpoint = self._sanitize_json(checkpoint_data) or {}
        safe_history = self._sanitize_json(step_history) or []

        record: dict[str, Any] = {
            "workflow_id": workflow_id,
            "mission_id": mission_id,
            "worker_id": worker_id,
            "platform": platform,
            "status": status or "pending",
            "current_step": int(current_step),
            "total_steps": int(total_steps),
            "checkpoint_data": safe_checkpoint,
            "step_history": safe_history,
            "created_at": now,
            "updated_at": now,
        }

        client = self._client()
        if client is not None:
            try:
                response = client.table(TABLE_NAME).insert(self._to_db_row(record)).execute()
                if response.data:
                    return {
                        "success": True,
                        "workflow": self._normalize_row(response.data[0], record),
                    }
            except Exception:  # pragma: no cover - defensive fallback
                pass

        # Fallback to in-memory storage
        self._memory_store[workflow_id] = record
        return {"success": True, "workflow": self._normalize_row(None, record)}

    def get(self, workflow_id: str) -> dict[str, Any] | None:
        """Retrieve a workflow by id.

        Args:
            workflow_id: The workflow identifier.

        Returns:
            Normalized workflow dictionary or ``None`` if not found.
        """
        client = self._client()
        if client is not None:
            try:
                response = (
                    client.table(TABLE_NAME)
                    .select("*")
                    .eq("id", workflow_id)
                    .limit(1)
                    .execute()
                )
                rows = response.data or []
                if rows:
                    return self._normalize_row(rows[0], None)
            except Exception:  # pragma: no cover - defensive fallback
                pass

        record = self._memory_store.get(workflow_id)
        if record is not None:
            return self._normalize_row(None, record)
        return None

    def update(
        self,
        workflow_id: str,
        *,
        status: str | None = None,
        current_step: int | None = None,
        checkpoint_data: dict[str, Any] | None = None,
        step_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Update mutable fields on an existing workflow.

        Returns:
            Dictionary with ``success`` flag and the updated normalized record.
        """
        if not workflow_id:
            return {"success": False, "error": "workflow_id is required"}

        updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if status is not None:
            updates["status"] = status
        if current_step is not None:
            updates["current_step"] = int(current_step)
        if checkpoint_data is not None:
            updates["checkpoint_data"] = self._sanitize_json(checkpoint_data) or {}
        if step_history is not None:
            updates["step_history"] = self._sanitize_json(step_history) or []

        client = self._client()
        if client is not None:
            try:
                response = (
                    client.table(TABLE_NAME)
                    .update(updates)
                    .eq("id", workflow_id)
                    .execute()
                )
                rows = response.data or []
                if rows:
                    return {
                        "success": True,
                        "workflow": self._normalize_row(rows[0], None),
                    }
            except Exception:  # pragma: no cover - defensive fallback
                pass

        # In-memory fallback
        existing = self._memory_store.get(workflow_id)
        if existing is None:
            return {
                "success": False,
                "error": f"Workflow {workflow_id} not found",
                "workflow_id": workflow_id,
            }
        existing.update(updates)
        self._memory_store[workflow_id] = existing
        return {
            "success": True,
            "workflow": self._normalize_row(None, existing),
        }

    def list_by_worker(
        self,
        worker_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List workflows for a worker.

        Args:
            worker_id: The worker identifier.
            status: Optional filter by workflow status.

        Returns:
            List of normalized workflow dictionaries.
        """
        results: list[dict[str, Any]] = []

        client = self._client()
        if client is not None:
            try:
                query = client.table(TABLE_NAME).select("*").eq("worker_id", worker_id)
                if status:
                    query = query.eq("status", status)
                response = query.execute()
                for row in response.data or []:
                    normalized = self._normalize_row(row, None)
                    if normalized:
                        results.append(normalized)
                return results
            except Exception:  # pragma: no cover - defensive fallback
                pass

        for record in self._memory_store.values():
            if record.get("worker_id") != worker_id:
                continue
            if status and record.get("status") != status:
                continue
            results.append(self._normalize_row(None, record))
        return results

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
    def _sanitize_json(value: Any) -> Any:
        """Return a JSON-safe copy of a value, dropping sensitive keys."""

        sensitive_keys = {
            "access_token",
            "refresh_token",
            "authorization_code",
            "oauth_code",
            "client_secret",
            "api_key",
            "token",
            "password",
        }

        def _clean(item: Any) -> Any:
            if isinstance(item, dict):
                cleaned: dict[str, Any] = {}
                for key, val in item.items():
                    if key.lower() in sensitive_keys:
                        continue
                    cleaned[key] = _clean(val)
                return cleaned
            if isinstance(item, list):
                return [_clean(v) for v in item]
            return item

        return _clean(value)

    @staticmethod
    def _to_db_row(record: dict[str, Any]) -> dict[str, Any]:
        """Convert a normalized record to a Supabase row payload."""
        return {
            "id": record["workflow_id"],
            "mission_id": record.get("mission_id"),
            "worker_id": record["worker_id"],
            "platform": record["platform"],
            "status": record["status"],
            "current_step": record["current_step"],
            "total_steps": record["total_steps"],
            "checkpoint_data": record.get("checkpoint_data") or {},
            "step_history": record.get("step_history") or [],
        }

    @staticmethod
    def _normalize_row(
        row: dict[str, Any] | None,
        fallback: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Produce a normalized dictionary that matches the connector contract."""
        if row is None and fallback is None:
            return None

        source = row if row is not None else fallback
        if source is None:
            return None

        checkpoint = source.get("checkpoint_data") or {}
        step_history = source.get("step_history") or []

        return {
            "workflow_id": source.get("id") or source.get("workflow_id"),
            "mission_id": source.get("mission_id"),
            "worker_id": source.get("worker_id"),
            "platform": source.get("platform"),
            "status": source.get("status"),
            "current_step": source.get("current_step"),
            "total_steps": source.get("total_steps"),
            "checkpoint_data": checkpoint,
            "step_history": step_history,
            "created_at": source.get("created_at"),
            "updated_at": source.get("updated_at"),
        }


__all__ = ["OnboardingWorkflowStore"]