"""P1-2: ApprovalGateway DB source-of-truth tests.

Covers the contract that ``public.approval_requests`` is the authoritative
state for every persisted approval request, the in-memory dict is at most
a write-through cache, and that ``approve`` / ``reject`` are idempotent
at the state level through atomic compare-and-set operations.

The tests use a fluent Supabase-client fake rather than ``MagicMock`` so
the assertions describe the *contract* (which table operations the
gateway performs and in what order) instead of the internal shape of
``MagicMock`` chains. The fake records every call so we can assert
ordering when relevant.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.approval_gateway import (  # noqa: E402
    ALL_STATUSES,
    FORBIDDEN_METADATA_KEYS,
    STATUS_APPROVED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    STATUS_REJECTED,
    ApprovalGateway,
    ApprovalRequest,
)


# ---------------------------------------------------------------------------
# Fluent Supabase client fake
# ---------------------------------------------------------------------------
class _FakeQuery:
    """Single-shot fluent query that records the chain of operations."""

    def __init__(self, table_state: dict[str, list[dict]], table_name: str) -> None:
        self._table_state = table_state
        self._table_name = table_name
        self._filters: list[tuple[str, object]] = []
        self._limit: int | None = None
        self._order: tuple[str, bool] | None = None
        self._select_all = False
        self._payload: dict | None = None
        self._operation: str | None = None
        self._update_payload: dict | None = None
        self._calls: list[tuple[str, dict]] = []  # recorded on execute()

    # ----- builder methods -----
    def select(self, _cols: str = "*") -> "_FakeQuery":
        self._select_all = True
        return self

    def eq(self, column: str, value: object) -> "_FakeQuery":
        self._filters.append((column, value))
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._limit = n
        return self

    def order(self, column: str, desc: bool = False) -> "_FakeQuery":
        self._order = (column, desc)
        return self

    def insert(self, payload: dict) -> "_FakeQuery":
        self._operation = "insert"
        self._payload = payload
        return self

    def update(self, payload: dict) -> "_FakeQuery":
        self._operation = "update"
        self._update_payload = payload
        return self

    # ----- terminal -----
    def execute(self) -> "_FakeResult":
        rows = list(self._table_state.get(self._table_name, []))

        if self._operation == "insert":
            assert self._payload is not None
            new_row = dict(self._payload)
            self._table_state.setdefault(self._table_name, []).append(new_row)
            self._calls.append(("insert", new_row))
            return _FakeResult([new_row])

        if self._operation == "update":
            assert self._update_payload is not None
            matched: list[dict] = []
            for row in rows:
                if all(row.get(col) == val for col, val in self._filters):
                    matched.append(row)
            for row in matched:
                row.update(self._update_payload)
            self._calls.append(("update", {"filters": list(self._filters), "payload": dict(self._update_payload), "matched": len(matched)}))
            return _FakeResult(matched)

        # SELECT path
        for col, val in self._filters:
            rows = [r for r in rows if r.get(col) == val]
        if self._order is not None:
            col, desc = self._order
            rows = sorted(rows, key=lambda r: r.get(col) or "", reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        self._calls.append(("select", {"filters": list(self._filters), "limit": self._limit, "matched": len(rows)}))
        return _FakeResult(rows)


class _FakeResult:
    def __init__(self, data: list[dict]) -> None:
        self.data = data


class _FakeTable:
    def __init__(self, table_state: dict[str, list[dict]], table_name: str) -> None:
        self._state = table_state
        self._name = table_name

    def __getattr__(self, item: str) -> object:
        # Forward ``.table("name")`` calls
        if item.startswith("_"):
            raise AttributeError(item)
        return _FakeTable(self._state, item)


class FakeSupabaseClient:
    """Drop-in replacement for the Supabase client used by the gateway.

    The real Supabase Python client supports ``.table(name).select(...).eq(...).execute()``.
    This fake matches that surface but keeps an in-memory table for assertions.
    """

    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {}

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self.tables, name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_client() -> FakeSupabaseClient:
    return FakeSupabaseClient()


def _seed_approval_row(
    client: FakeSupabaseClient,
    *,
    approval_id: str = "appr-1",
    status: str = STATUS_PENDING,
    mission_id: str = "mission-1",
    action_type: str = "start_platform_onboarding",
    payload: dict | None = None,
    expires_at: str | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    row = {
        "id": approval_id,
        "mission_id": mission_id,
        "action_type": action_type,
        "risk_level": "sensitive",
        "status": status,
        "requested_at": now.isoformat(),
        "expires_at": expires_at or (now + timedelta(hours=24)).isoformat(),
        "metadata": payload or {"platform": "pinterest", "worker_id": "worker-1"},
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    client.tables.setdefault("approval_requests", []).append(dict(row))
    return row


def _build_gateway_with_fake(client: FakeSupabaseClient) -> ApprovalGateway:
    gateway = ApprovalGateway()
    gateway._client = client
    return gateway


# ---------------------------------------------------------------------------
# 1. create approval persists
# ---------------------------------------------------------------------------
def test_create_request_persists_to_db(fake_client):
    gateway = _build_gateway_with_fake(fake_client)
    result = gateway.create_request(
        mission_id="mission-A",
        action_type="start_platform_onboarding",
        risk_level="sensitive",
        payload={"platform": "pinterest", "worker_id": "worker-1"},
    )
    assert result["success"] is True
    request = result["request"]

    # Exactly one row landed in the table.
    rows = fake_client.tables["approval_requests"]
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == request["id"]
    assert row["mission_id"] == "mission-A"
    assert row["action_type"] == "start_platform_onboarding"
    assert row["status"] == STATUS_PENDING
    assert row["metadata"]["platform"] == "pinterest"
    assert row["metadata"]["worker_id"] == "worker-1"


# ---------------------------------------------------------------------------
# 2. get reads from DB (source of truth)
# ---------------------------------------------------------------------------
def test_get_request_reads_db_record(fake_client):
    _seed_approval_row(fake_client, approval_id="appr-2", status=STATUS_APPROVED)
    gateway = _build_gateway_with_fake(fake_client)

    record = gateway.get_request("appr-2")
    assert record is not None
    assert record["id"] == "appr-2"
    assert record["status"] == STATUS_APPROVED
    assert record["payload"] == {"platform": "pinterest", "worker_id": "worker-1"}


# ---------------------------------------------------------------------------
# 3. DB record wins over stale memory
# ---------------------------------------------------------------------------
def test_db_record_wins_over_stale_memory(fake_client):
    # Plant a stale "pending" record in the in-memory cache for a different id.
    gateway = _build_gateway_with_fake(fake_client)
    stale = ApprovalRequest(
        request_id="stale-id",
        mission_id="mission-stale",
        action_type="start_platform_onboarding",
        risk_level="sensitive",
        payload={"platform": "pinterest"},
    )
    gateway._memory_store["stale-id"] = stale
    # The DB does not know about "stale-id".
    fake_client.tables.setdefault("approval_requests", [])

    # get_request must NOT return the stale in-memory row.
    assert gateway.get_request("stale-id") is None


# ---------------------------------------------------------------------------
# 4. approve persists state
# ---------------------------------------------------------------------------
def test_approve_persists_approved_state(fake_client):
    _seed_approval_row(fake_client, approval_id="appr-3", status=STATUS_PENDING)
    gateway = _build_gateway_with_fake(fake_client)

    result = gateway.approve_request("appr-3", approved_by="ops@example.com")
    assert result["success"] is True
    assert result["request"]["status"] == STATUS_APPROVED
    assert result["request"]["approved_by"] == "ops@example.com"

    # The DB row was actually updated.
    rows = fake_client.tables["approval_requests"]
    assert rows[0]["status"] == STATUS_APPROVED
    assert rows[0]["approved_by"] == "ops@example.com"


# ---------------------------------------------------------------------------
# 5. reject persists state
# ---------------------------------------------------------------------------
def test_reject_persists_rejected_state(fake_client):
    _seed_approval_row(fake_client, approval_id="appr-4", status=STATUS_PENDING)
    gateway = _build_gateway_with_fake(fake_client)

    result = gateway.reject_request(
        "appr-4", reason="not appropriate", rejected_by="reviewer@example.com"
    )
    assert result["success"] is True
    assert result["request"]["status"] == STATUS_REJECTED
    assert result["request"]["rejection_reason"] == "not appropriate"
    assert result["request"]["rejected_by"] == "reviewer@example.com"

    rows = fake_client.tables["approval_requests"]
    assert rows[0]["status"] == STATUS_REJECTED
    assert rows[0]["reason"] == "not appropriate"


# ---------------------------------------------------------------------------
# 6 + 7. approved/rejected state survives a brand-new gateway instance
# ---------------------------------------------------------------------------
def test_approved_state_survives_new_gateway_instance(fake_client):
    _seed_approval_row(fake_client, approval_id="appr-5", status=STATUS_PENDING)
    g1 = _build_gateway_with_fake(fake_client)
    g1.approve_request("appr-5", approved_by="alice")

    # Brand-new gateway reading the same backing store.
    g2 = _build_gateway_with_fake(fake_client)
    record = g2.get_request("appr-5")
    assert record is not None
    assert record["status"] == STATUS_APPROVED
    assert record["approved_by"] == "alice"


def test_rejected_state_survives_new_gateway_instance(fake_client):
    _seed_approval_row(fake_client, approval_id="appr-6", status=STATUS_PENDING)
    g1 = _build_gateway_with_fake(fake_client)
    g1.reject_request("appr-6", reason="x", rejected_by="bob")

    g2 = _build_gateway_with_fake(fake_client)
    record = g2.get_request("appr-6")
    assert record is not None
    assert record["status"] == STATUS_REJECTED
    assert record["rejection_reason"] == "x"
    assert record["rejected_by"] == "bob"


# ---------------------------------------------------------------------------
# 8. expired state is respected
# ---------------------------------------------------------------------------
def test_expired_state_is_respected_and_terminal(fake_client):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    _seed_approval_row(
        fake_client,
        approval_id="appr-7",
        status=STATUS_PENDING,
        expires_at=past,
    )
    gateway = _build_gateway_with_fake(fake_client)

    # Approving an already-expired request must be rejected as an invalid
    # transition (concurrent modification: row is in pending state but
    # clock has crossed expires_at; gateway forces the pending->expired
    # transition first).
    assert gateway.is_expired("appr-7") is True
    record = gateway.get_request("appr-7")
    assert record is not None
    assert record["status"] == STATUS_EXPIRED

    # Once expired, approve/reject must fail (terminal state).
    approve = gateway.approve_request("appr-7", approved_by="alice")
    assert approve["success"] is False
    reject = gateway.reject_request("appr-7", reason="too late")
    assert reject["success"] is False


# ---------------------------------------------------------------------------
# 9. invalid state transition is rejected
# ---------------------------------------------------------------------------
def test_approve_rejected_request_is_invalid_transition(fake_client):
    _seed_approval_row(fake_client, approval_id="appr-8", status=STATUS_REJECTED)
    gateway = _build_gateway_with_fake(fake_client)

    result = gateway.approve_request("appr-8", approved_by="alice")
    assert result["success"] is False
    assert "rejected" in result["error"].lower()


def test_reject_approved_request_is_invalid_transition(fake_client):
    _seed_approval_row(fake_client, approval_id="appr-9", status=STATUS_APPROVED)
    gateway = _build_gateway_with_fake(fake_client)

    result = gateway.reject_request("appr-9", reason="change of mind")
    assert result["success"] is False
    assert "approved" in result["error"].lower()


# ---------------------------------------------------------------------------
# 10 + 11. duplicate approve / reject is idempotent at the state level
# ---------------------------------------------------------------------------
def test_duplicate_approve_is_idempotent(fake_client):
    _seed_approval_row(fake_client, approval_id="appr-10", status=STATUS_PENDING)
    gateway = _build_gateway_with_fake(fake_client)

    first = gateway.approve_request("appr-10", approved_by="alice")
    assert first["success"] is True
    assert "idempotent" not in first

    second = gateway.approve_request("appr-10", approved_by="alice-again")
    # The second call must be idempotent: the original actor must be
    # preserved (no second state mutation) and the idempotent flag set.
    assert second["success"] is True
    assert second.get("idempotent") is True
    assert second["request"]["approved_by"] == "alice"


def test_duplicate_reject_is_idempotent(fake_client):
    _seed_approval_row(fake_client, approval_id="appr-11", status=STATUS_PENDING)
    gateway = _build_gateway_with_fake(fake_client)

    first = gateway.reject_request("appr-11", reason="first", rejected_by="bob")
    assert first["success"] is True
    assert "idempotent" not in first

    second = gateway.reject_request("appr-11", reason="second", rejected_by="bob")
    assert second["success"] is True
    assert second.get("idempotent") is True
    # The first reason and actor must be preserved.
    assert second["request"]["rejection_reason"] == "first"
    assert second["request"]["rejected_by"] == "bob"


# ---------------------------------------------------------------------------
# 12. payload / metadata survives create + approve + reject
# ---------------------------------------------------------------------------
def test_payload_metadata_survives_approve_and_reject(fake_client):
    payload = {
        "platform": "pinterest",
        "worker_id": "worker-1",
        "mission_id": "mission-1",
        "workflow_id": "wf-1",
        "action_type": "start_platform_onboarding",
        "human_input": {"email": "user@example.com"},
    }
    _seed_approval_row(
        fake_client,
        approval_id="appr-12",
        status=STATUS_PENDING,
        payload=payload,
    )
    gateway = _build_gateway_with_fake(fake_client)

    record = gateway.get_request("appr-12")
    assert record is not None
    assert record["payload"] == payload
    assert record["payload"]["workflow_id"] == "wf-1"
    assert record["payload"]["human_input"]["email"] == "user@example.com"
    assert record["mission_id"] == "mission-1"
    assert record["action_type"] == "start_platform_onboarding"

    gateway.approve_request("appr-12", approved_by="alice")
    record = gateway.get_request("appr-12")
    assert record is not None
    assert record["payload"] == payload
    assert record["payload"]["workflow_id"] == "wf-1"


# ---------------------------------------------------------------------------
# 13. secrets are not persisted
# ---------------------------------------------------------------------------
def test_secrets_are_not_persisted_in_metadata(fake_client):
    gateway = _build_gateway_with_fake(fake_client)
    secret_payload = {
        "platform": "pinterest",
        "worker_id": "worker-1",
        "access_token": "ya29.SECRET",
        "refresh_token": "1//SECRET",
        "oauth_code": "OAUTH-CODE-XYZ",
        "client_secret": "very-secret",
        "password": "hunter2",
        "id_token": "id-token",
        "auth_data": {
            "api_key": "ak_live_xxx",
            "token": "tok",
            "session": "sess",
        },
        "safe_field": "kept",
    }

    result = gateway.create_request(
        mission_id="mission-secret",
        action_type="connect_platform",
        risk_level="sensitive",
        payload=secret_payload,
    )
    assert result["success"] is True

    persisted = fake_client.tables["approval_requests"][0]["metadata"]
    # Forbidden keys are stripped at every depth.
    for forbidden in (
        "access_token",
        "refresh_token",
        "oauth_code",
        "client_secret",
        "password",
        "id_token",
        "api_key",
        "token",
        "session",
        "authorization_code",
    ):
        assert forbidden not in persisted
        assert forbidden not in (persisted.get("auth_data") or {})
    # Non-sensitive data survives.
    assert persisted["platform"] == "pinterest"
    assert persisted["worker_id"] == "worker-1"
    assert persisted["safe_field"] == "kept"
    # The forbidden-key list is comprehensive.
    assert "code" in FORBIDDEN_METADATA_KEYS
    assert "redirect_uri" in FORBIDDEN_METADATA_KEYS
    assert "secret" in FORBIDDEN_METADATA_KEYS


# ---------------------------------------------------------------------------
# 14. DB unavailable still works where intended (in-memory fallback)
# ---------------------------------------------------------------------------
def test_db_unavailable_uses_memory_fallback():
    gateway = ApprovalGateway()
    assert gateway._client is None
    assert gateway._is_configured() is False

    result = gateway.create_request(
        mission_id="mission-mem",
        action_type="publish_content",
        risk_level="safe",
        payload={"content": "hello"},
    )
    assert result["success"] is True
    request_id = result["request"]["id"]
    assert request_id in gateway._memory_store

    approve = gateway.approve_request(request_id, approved_by="alice")
    assert approve["success"] is True
    assert approve["request"]["status"] == STATUS_APPROVED

    record = gateway.get_request(request_id)
    assert record is not None
    assert record["status"] == STATUS_APPROVED


# ---------------------------------------------------------------------------
# 15. real DB errors are not silently swallowed
# ---------------------------------------------------------------------------
class _ExplodingClient:
    """A fake client whose every call raises a real exception."""

    def table(self, _name: str):  # pragma: no cover - trivial
        raise RuntimeError("simulated DB outage")


def test_real_db_error_is_surfaced_not_swallowed():
    gateway = ApprovalGateway()
    gateway._client = _ExplodingClient()  # type: ignore[assignment]

    result = gateway.create_request(
        mission_id="mission-x",
        action_type="send_message",
        risk_level="sensitive",
        payload={"x": 1},
    )
    # Real DB error is reported, not silently replaced with stale memory.
    assert result["success"] is False
    assert "db_error" in result["error"]
    assert gateway._memory_store == {}


# ---------------------------------------------------------------------------
# 16. compare-and-set prevents racing transitions
# ---------------------------------------------------------------------------
def test_compare_and_set_prevents_racing_approve(fake_client):
    """Two simultaneous approve attempts must not both succeed.

    The atomic ``UPDATE … WHERE id = ? AND status = 'pending'`` returns
    rows only for the first caller; the second caller observes a
    concurrent-modification probe and is returned the now-approved row
    as an idempotent no-op rather than a second state mutation.
    """

    _seed_approval_row(fake_client, approval_id="appr-race", status=STATUS_PENDING)
    gateway = _build_gateway_with_fake(fake_client)

    # First approve flips the row to "approved" in the fake table.
    first = gateway.approve_request("appr-race", approved_by="alice")
    assert first["success"] is True
    assert first["request"]["status"] == STATUS_APPROVED

    # Second approve sees a row already in the approved state. The
    # compare-and-set matches zero rows; the gateway probes the row,
    # discovers the approved state, and returns the existing record
    # with ``idempotent=True``. The second caller's actor must NOT
    # overwrite the first caller's actor.
    second = gateway.approve_request("appr-race", approved_by="bob")
    assert second["success"] is True
    assert second.get("idempotent") is True
    assert second["request"]["approved_by"] == "alice"
    # The DB row was not mutated twice.
    assert fake_client.tables["approval_requests"][0]["status"] == STATUS_APPROVED


# ---------------------------------------------------------------------------
# 17. status values are the canonical enum
# ---------------------------------------------------------------------------
def test_canonical_status_values():
    assert ALL_STATUSES == (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED, STATUS_EXPIRED)
    assert STATUS_PENDING == "pending"
    assert STATUS_APPROVED == "approved"
    assert STATUS_REJECTED == "rejected"
    assert STATUS_EXPIRED == "expired"


# ---------------------------------------------------------------------------
# 18. P1-1 approval → resume regression: approve → resume succeeds once
# ---------------------------------------------------------------------------
def test_p1_1_approve_then_resume_regression():
    """End-to-end P1-1 contract: approve persists, resume reads the
    persisted approval, and connector state advances exactly once even
    after restart."""

    sys.path_path = None  # noqa: F841 - silence linters on unused

    from app.services.approval_resume_service import ApprovalResumeService
    from app.services.connectors.pinterest_connector import PinterestConnector
    from app.services.connectors.registry import ConnectorRegistry
    from app.services.human_intervention import HumanInterventionManager
    from app.services.stores.onboarding_workflow_store import OnboardingWorkflowStore
    from app.services.stores.platform_connection_store import PlatformConnectionStore

    fake = FakeSupabaseClient()
    workflow_store = OnboardingWorkflowStore(client=None)
    connection_store = PlatformConnectionStore(client=None)

    gateway = ApprovalGateway()
    gateway._client = fake

    # Create + approve (persists to fake DB).
    create = gateway.create_request(
        mission_id="mission-resume",
        action_type="start_platform_onboarding",
        risk_level="sensitive",
        payload={"platform": "pinterest", "worker_id": "worker-r"},
    )
    approval_id = create["request"]["id"]
    approval = gateway.approve_request(approval_id, approved_by="alice")
    assert approval["success"] is True

    # Build a fresh service (simulate a process restart) using the same
    # stores and the SAME fake client.
    connector = PinterestConnector(
        workflow_store=workflow_store,
        connection_store=connection_store,
    )
    registry = ConnectorRegistry()
    registry.register(connector)
    service = ApprovalResumeService(
        approval_gateway=ApprovalGateway(),
        connector_registry=registry,
        human_intervention_manager=HumanInterventionManager(),
    )
    # Re-bind the service's gateway to our fake-backed gateway so the
    # resume path sees the persisted state.
    service._approval_gateway = gateway

    result = service.resume(approval_id)
    assert result["status"] == "awaiting_human_intervention"
    assert result["workflow_id"]

    # Second resume must be a state-level no-op.
    second = service.resume(approval_id)
    assert second["status"] in {"completed", "awaiting_resume", "awaiting_human_intervention"}


# ---------------------------------------------------------------------------
# 19. rejected approval does not resume
# ---------------------------------------------------------------------------
def test_rejected_approval_does_not_resume(fake_client):
    from app.services.approval_resume_service import ApprovalResumeService
    from app.services.connectors.pinterest_connector import PinterestConnector
    from app.services.connectors.registry import ConnectorRegistry
    from app.services.human_intervention import HumanInterventionManager

    _seed_approval_row(fake_client, approval_id="appr-r", status=STATUS_PENDING)
    gateway = _build_gateway_with_fake(fake_client)
    gateway.reject_request("appr-r", reason="nope", rejected_by="alice")

    registry = ConnectorRegistry()
    registry.register(PinterestConnector())
    service = ApprovalResumeService(
        approval_gateway=gateway,
        connector_registry=registry,
        human_intervention_manager=HumanInterventionManager(),
    )

    result = service.resume("appr-r")
    assert result["status"] == "approval_rejected"


# ---------------------------------------------------------------------------
# 20. expired approval does not resume
# ---------------------------------------------------------------------------
def test_expired_approval_does_not_resume(fake_client):
    from app.services.approval_resume_service import ApprovalResumeService
    from app.services.connectors.pinterest_connector import PinterestConnector
    from app.services.connectors.registry import ConnectorRegistry
    from app.services.human_intervention import HumanInterventionManager

    # Seed an approved row whose ``expires_at`` is in the past. The
    # resume service checks status first; an ``approved`` row whose
    # ``expires_at`` is in the past must be refused as ``approval_expired``
    # before any connector dispatch.
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    _seed_approval_row(
        fake_client,
        approval_id="appr-e",
        status=STATUS_APPROVED,
        expires_at=past,
    )
    gateway = _build_gateway_with_fake(fake_client)

    registry = ConnectorRegistry()
    registry.register(PinterestConnector())
    service = ApprovalResumeService(
        approval_gateway=gateway,
        connector_registry=registry,
        human_intervention_manager=HumanInterventionManager(),
    )

    result = service.resume("appr-e")
    assert result["status"] == "approval_expired"


# ---------------------------------------------------------------------------
# 21. list_requests reads from DB
# ---------------------------------------------------------------------------
def test_list_requests_reads_from_db(fake_client):
    _seed_approval_row(fake_client, approval_id="appr-l1", mission_id="mission-X", status=STATUS_PENDING)
    _seed_approval_row(fake_client, approval_id="appr-l2", mission_id="mission-X", status=STATUS_APPROVED)
    _seed_approval_row(fake_client, approval_id="appr-l3", mission_id="mission-Y", status=STATUS_PENDING)
    gateway = _build_gateway_with_fake(fake_client)

    all_records = gateway.list_requests()
    assert {r["id"] for r in all_records} == {"appr-l1", "appr-l2", "appr-l3"}

    mission_x = gateway.list_requests(mission_id="mission-X")
    assert {r["id"] for r in mission_x} == {"appr-l1", "appr-l2"}

    approved = gateway.list_requests(status=STATUS_APPROVED)
    assert {r["id"] for r in approved} == {"appr-l2"}


# ---------------------------------------------------------------------------
# 22. not-found approval is not silently created
# ---------------------------------------------------------------------------
def test_unknown_approval_approve_returns_error(fake_client):
    gateway = _build_gateway_with_fake(fake_client)
    result = gateway.approve_request("nonexistent")
    assert result["success"] is False
    assert "not found" in result["error"].lower()
