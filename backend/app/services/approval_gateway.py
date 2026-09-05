"""Approval gateway service for human approval workflows.

This module provides a lightweight approval request management system for
sensitive actions that require human review before execution. The implementation
is defensive and supports both in-memory and database-backed storage.

The database schema includes:
- approval_requests table with persistent state
- In-memory fallback for testing and database unavailability
- Support for approved_by and rejected_by tracking
- Expiration logic compatible with TTL management
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

try:
    from .. import database as database_module
except Exception:  # pragma: no cover - fallback for missing runtime config
    try:
        from backend.app import database as database_module
    except Exception:  # pragma: no cover - fallback for direct execution
        database_module = None


class ApprovalRequest:
    """Represents a single approval request."""

    def __init__(
        self,
        request_id: str,
        mission_id: str,
        action_type: str,
        risk_level: str,
        payload: dict[str, Any],
        created_at: datetime | None = None,
        status: str = "pending",
        expires_at: datetime | None = None,
        approved_at: datetime | None = None,
        rejected_at: datetime | None = None,
        approved_by: str | None = None,
        rejected_by: str | None = None,
        rejection_reason: str | None = None,
    ):
        """Initialize an approval request.

        Args:
            request_id: Unique request identifier.
            mission_id: Associated mission identifier.
            action_type: The type of action requiring approval.
            risk_level: Risk classification (safe, moderate, sensitive).
            payload: Action payload data.
            created_at: Request creation timestamp.
            status: Current approval status (pending, approved, rejected, expired).
            expires_at: When this request expires.
            approved_at: When the request was approved.
            rejected_at: When the request was rejected.
            approved_by: User who approved the request.
            rejected_by: User who rejected the request.
            rejection_reason: Reason for rejection.
        """
        self.request_id = request_id
        self.mission_id = mission_id
        self.action_type = action_type
        self.risk_level = risk_level
        self.payload = payload
        self.created_at = created_at or datetime.now(timezone.utc)
        self.status = status
        self.expires_at = expires_at or (self.created_at + timedelta(hours=24))
        self.approved_at = approved_at
        self.rejected_at = rejected_at
        self.approved_by = approved_by
        self.rejected_by = rejected_by
        self.rejection_reason = rejection_reason

    def to_dict(self) -> dict[str, Any]:
        """Convert request to dictionary.

        Returns:
            Dictionary representation of the request.
        """
        return {
            "id": self.request_id,
            "mission_id": self.mission_id,
            "action_type": self.action_type,
            "risk_level": self.risk_level,
            "status": self.status,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "approved_by": self.approved_by,
            "rejected_by": self.rejected_by,
            "rejection_reason": self.rejection_reason,
        }


class ApprovalGateway:
    """Manage approval requests for sensitive actions."""

    def __init__(self) -> None:
        """Initialize the approval gateway with optional database support."""
        self._client = self._get_client()
        # In-memory store for requests (for testing and fallback)
        self._memory_store: dict[str, ApprovalRequest] = {}

    def create_request(
        self,
        mission_id: str,
        action_type: str,
        risk_level: str,
        payload: dict[str, Any],
        ttl_hours: int = 24,
    ) -> dict[str, Any]:
        """Create a new approval request.

        Args:
            mission_id: Associated mission identifier.
            action_type: Type of action requiring approval.
            risk_level: Risk level classification.
            payload: Action payload data.
            ttl_hours: Time-to-live in hours.

        Returns:
            Dictionary with success status and request details.
        """
        request_id = str(uuid4())
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=ttl_hours)

        request = ApprovalRequest(
            request_id=request_id,
            mission_id=mission_id,
            action_type=action_type,
            risk_level=risk_level,
            payload=payload,
            created_at=now,
            expires_at=expires_at,
        )

        # Try to persist to database
        if self._client:
            try:
                db_payload = {
                    "id": request_id,
                    "mission_id": mission_id,
                    "action_type": action_type,
                    "risk_level": risk_level,
                    "status": "pending",
                    "requested_at": now.isoformat(),
                    "expires_at": expires_at.isoformat(),
                    "metadata": payload,
                }
                response = self._client.table("approval_requests").insert(db_payload).execute()
                if response.data:
                    return {"success": True, "request": request.to_dict()}
            except Exception:  # pragma: no cover - defensive fallback
                pass

        # Store in memory as fallback
        self._memory_store[request_id] = request
        return {"success": True, "request": request.to_dict()}

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        """Retrieve an approval request by ID.

        Args:
            request_id: The request identifier.

        Returns:
            Request details or None if not found.
        """
        # Check database first
        if self._client:
            try:
                response = self._client.table("approval_requests").select("*").eq("id", request_id).limit(1).execute()
                if response.data:
                    row = response.data[0]
                    return self._normalize_request(row)
            except Exception:  # pragma: no cover - defensive fallback
                pass

        # Check memory store
        request = self._memory_store.get(request_id)
        if request:
            return request.to_dict()

        return None

    def list_requests(
        self,
        mission_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List approval requests with optional filtering.

        Args:
            mission_id: Optional filter by mission ID.
            status: Optional filter by status.
            limit: Maximum number of results.

        Returns:
            List of approval request dictionaries.
        """
        requests = []

        # Try to get from database
        if self._client:
            try:
                query = self._client.table("approval_requests").select("*")
                if mission_id:
                    query = query.eq("mission_id", mission_id)
                if status:
                    query = query.eq("status", status)
                query = query.order("requested_at", desc=True).limit(limit)
                response = query.execute()
                if response.data:
                    for row in response.data:
                        normalized = self._normalize_request(row)
                        if normalized:
                            requests.append(normalized)
                    return requests
            except Exception:  # pragma: no cover - defensive fallback
                pass

        # Fallback to memory store
        for request in self._memory_store.values():
            request_dict = request.to_dict()
            if mission_id and request_dict["mission_id"] != mission_id:
                continue
            if status and request_dict["status"] != status:
                continue
            requests.append(request_dict)

        # Sort by created_at descending
        requests.sort(key=lambda r: r["created_at"], reverse=True)
        return requests[:limit]

    def approve_request(self, request_id: str, approved_by: str | None = None) -> dict[str, Any]:
        """Approve an approval request.

        Args:
            request_id: The request identifier.
            approved_by: Optional identifier of the user approving the request.

        Returns:
            Dictionary with success status and updated request.
        """
        request = self._memory_store.get(request_id)
        if not request:
            # Try to fetch from database
            db_request = self.get_request(request_id)
            if not db_request:
                return {"success": False, "error": f"Request {request_id} not found"}
            # Load from database result
            request = ApprovalRequest(
                request_id=db_request["id"],
                mission_id=db_request["mission_id"],
                action_type=db_request["action_type"],
                risk_level=db_request["risk_level"],
                payload=db_request["payload"],
                status=db_request["status"],
                created_at=datetime.fromisoformat(db_request["created_at"]) if db_request.get("created_at") else None,
                expires_at=datetime.fromisoformat(db_request["expires_at"]) if db_request.get("expires_at") else None,
            )

        if request.status != "pending":
            return {"success": False, "error": f"Request is {request.status}, cannot approve"}

        now = datetime.now(timezone.utc)
        request.status = "approved"
        request.approved_at = now
        request.approved_by = approved_by
        self._memory_store[request_id] = request

        # Update in database if available
        if self._client:
            try:
                self._client.table("approval_requests").update(
                    {
                        "status": "approved",
                        "approved_at": now.isoformat(),
                        "approved_by": approved_by,
                        "updated_at": now.isoformat(),
                    }
                ).eq("id", request_id).execute()
            except Exception:  # pragma: no cover - defensive fallback
                pass

        return {"success": True, "request": request.to_dict()}

    def reject_request(self, request_id: str, reason: str = "", rejected_by: str | None = None) -> dict[str, Any]:
        """Reject an approval request.

        Args:
            request_id: The request identifier.
            reason: Optional reason for rejection.
            rejected_by: Optional identifier of the user rejecting the request.

        Returns:
            Dictionary with success status and updated request.
        """
        request = self._memory_store.get(request_id)
        if not request:
            # Try to fetch from database
            db_request = self.get_request(request_id)
            if not db_request:
                return {"success": False, "error": f"Request {request_id} not found"}
            # Load from database result
            request = ApprovalRequest(
                request_id=db_request["id"],
                mission_id=db_request["mission_id"],
                action_type=db_request["action_type"],
                risk_level=db_request["risk_level"],
                payload=db_request["payload"],
                status=db_request["status"],
                created_at=datetime.fromisoformat(db_request["created_at"]) if db_request.get("created_at") else None,
                expires_at=datetime.fromisoformat(db_request["expires_at"]) if db_request.get("expires_at") else None,
            )

        if request.status != "pending":
            return {"success": False, "error": f"Request is {request.status}, cannot reject"}

        now = datetime.now(timezone.utc)
        request.status = "rejected"
        request.rejected_at = now
        request.rejection_reason = reason
        request.rejected_by = rejected_by
        self._memory_store[request_id] = request

        # Update in database if available
        if self._client:
            try:
                self._client.table("approval_requests").update(
                    {
                        "status": "rejected",
                        "rejected_at": now.isoformat(),
                        "rejected_by": rejected_by,
                        "reason": reason,
                        "updated_at": now.isoformat(),
                    }
                ).eq("id", request_id).execute()
            except Exception:  # pragma: no cover - defensive fallback
                pass

        return {"success": True, "request": request.to_dict()}

    def is_approved(self, request_id: str) -> bool:
        """Check if a request is approved.

        Args:
            request_id: The request identifier.

        Returns:
            True if request is approved, False otherwise.
        """
        request = self.get_request(request_id)
        if not request:
            return False
        return request.get("status") == "approved"

    def is_expired(self, request_id: str) -> bool:
        """Check if a request has expired.

        Args:
            request_id: The request identifier.

        Returns:
            True if request has expired, False otherwise.
        """
        request = self.get_request(request_id)
        if not request:
            return False

        if request.get("status") == "expired":
            return True

        try:
            expires_at = datetime.fromisoformat(request["expires_at"])
            if datetime.now(timezone.utc) > expires_at:
                # Mark as expired
                self._mark_expired(request_id)
                return True
        except Exception:  # pragma: no cover - defensive handling
            pass

        return False

    def _mark_expired(self, request_id: str) -> None:
        """Mark a request as expired.

        Args:
            request_id: The request identifier.
        """
        request = self._memory_store.get(request_id)
        if request:
            request.status = "expired"
            self._memory_store[request_id] = request

        # Update in database if available
        if self._client:
            try:
                now = datetime.now(timezone.utc)
                self._client.table("approval_requests").update(
                    {
                        "status": "expired",
                        "updated_at": now.isoformat(),
                    }
                ).eq("id", request_id).execute()
            except Exception:  # pragma: no cover - defensive fallback
                pass

    def _get_client(self) -> Any:
        """Get the Supabase client if available.

        Returns:
            Supabase client or None if not configured.
        """
        if not database_module:
            return None
        return getattr(database_module, "supabase_client", None)

    def _normalize_request(self, row: dict[str, Any]) -> dict[str, Any]:
        """Normalize a database row into standard format.

        Args:
            row: Database row data.

        Returns:
            Normalized request dictionary.
        """
        # Handle both requested_at and created_at for compatibility
        created_at = row.get("created_at") or row.get("requested_at")

        return {
            "id": row.get("id"),
            "mission_id": row.get("mission_id"),
            "action_type": row.get("action_type"),
            "risk_level": row.get("risk_level"),
            "status": row.get("status", "pending"),
            "payload": row.get("metadata", {}),
            "created_at": created_at,
            "expires_at": row.get("expires_at"),
            "approved_at": row.get("approved_at"),
            "rejected_at": row.get("rejected_at"),
            "approved_by": row.get("approved_by"),
            "rejected_by": row.get("rejected_by"),
            "rejection_reason": row.get("reason"),
        }

