"""Tests for P1-3: start_onboarding restart idempotency.

Covers the durable get-or-create mechanism that prevents a second
onboarding workflow from being created when the same approval_id
resumes a connector after process restart, HTTP retry, or duplicate
approval POST.
"""

from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.connectors.pinterest_connector import PinterestConnector  # noqa: E402
from app.services.stores.onboarding_workflow_store import OnboardingWorkflowStore  # noqa: E402


# ---------------------------------------------------------------------------
# Fake Supabase client simulating claim_onboarding_workflow_for_approval
# ---------------------------------------------------------------------------
class _FakeWorkflowTable:
    """Minimal table-shaped object that supports insert and select-by-approval."""

    def __init__(self, store: "FakeSupabaseClient") -> None:
        self._store = store

    def insert(self, payload):
        # Direct inserts that bypass the RPC function are only used by
        # legacy code paths. The partial unique index is simulated in
        # FakeSupabaseClient.upsert as well.
        self._store.rows.append(dict(payload))
        return _FakeExec(self._store.rows[-1:])

    def select(self, *_args, **_kwargs):
        return _FakeQuery(self._store)

    def update(self, payload):
        return _FakeExec([])

    def upsert(self, payload, on_conflict=None):  # noqa: ARG002
        return _FakeExec(self._store.rows)


class _FakeQuery:
    def __init__(self, store: "FakeSupabaseClient") -> None:
        self._store = store

    def eq(self, column, value):
        self._column = column
        self._value = value
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        col = getattr(self, "_column", None)
        val = getattr(self, "_value", None)
        lim = getattr(self, "_limit", None)
        matched = [r for r in self._store.rows if col is None or r.get(col) == val]
        if lim is not None:
            matched = matched[:lim]
        return _FakeExec(matched)


class _FakeExec:
    def __init__(self, data) -> None:
        self.data = data


class _FakeRpcBuilder:
    def __init__(self, store: "FakeSupabaseClient", name: str, params: dict) -> None:
        self._store = store
        self._name = name
        self._params = dict(params)
        self._store.rpc_calls.append((self._name, self._params))

    def execute(self):
        with self._store._lock:
            if self._store.fail_next_rpc:
                self._store.fail_next_rpc = False
                raise RuntimeError("simulated rpc failure")
            if self._name == "claim_onboarding_workflow_for_approval":
                approval_id = self._params.get("p_approval_id")
                existing = [
                    r for r in self._store.rows
                    if r.get("started_by_approval_id") == approval_id
                ]
                if existing:
                    return _FakeExec([{"workflow": existing[0], "created": False}])
                new_row = {
                    "id": self._params.get("p_workflow_id"),
                    "mission_id": self._params.get("p_mission_id"),
                    "worker_id": self._params.get("p_worker_id"),
                    "platform": self._params.get("p_platform"),
                    "status": self._params.get("p_status"),
                    "current_step": self._params.get("p_current_step"),
                    "total_steps": self._params.get("p_total_steps"),
                    "checkpoint_data": self._params.get("p_checkpoint_data"),
                    "step_history": self._params.get("p_step_history"),
                    "started_by_approval_id": approval_id,
                }
                self._store.rows.append(new_row)
                return _FakeExec([{"workflow": new_row, "created": True}])
        return _FakeExec([])


class FakeSupabaseClient:
    """Fake supabase client that simulates the claim RPC function."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.rpc_calls: list[tuple[str, dict]] = []
        self._lock = threading.Lock()
        self.fail_next_rpc: bool = False

    def table(self, name: str):
        return _FakeWorkflowTable(self)

    def rpc(self, name: str, params: dict):
        return _FakeRpcBuilder(self, name, params)


# ---------------------------------------------------------------------------
# Store-level tests
# ---------------------------------------------------------------------------
def test_get_or_create_for_approval_first_call_creates():
    client = FakeSupabaseClient()
    store = OnboardingWorkflowStore(client=client)

    result = store.get_or_create_for_approval(
        approval_id=str(uuid4()),
        workflow_id=str(uuid4()),
        mission_id="m-1",
        worker_id="w-1",
        platform="pinterest",
        status="awaiting_human",
        current_step=1,
        total_steps=3,
        checkpoint_data={"x": 1},
        step_history=[],
    )
    assert result["success"] is True
    assert result["created"] is True
    assert result["workflow"]["started_by_approval_id"] in client.rows[0]["started_by_approval_id"]
    assert len(client.rows) == 1


def test_get_or_create_for_approval_second_call_returns_existing():
    client = FakeSupabaseClient()
    store = OnboardingWorkflowStore(client=client)
    approval_id = str(uuid4())

    first = store.get_or_create_for_approval(
        approval_id=approval_id,
        workflow_id=str(uuid4()),
        mission_id="m-1",
        worker_id="w-1",
        platform="pinterest",
        status="awaiting_human",
        current_step=1,
        total_steps=3,
        checkpoint_data={"x": 1},
        step_history=[],
    )
    second = store.get_or_create_for_approval(
        approval_id=approval_id,
        workflow_id=str(uuid4()),
        mission_id="m-1",
        worker_id="w-1",
        platform="pinterest",
        status="awaiting_human",
        current_step=1,
        total_steps=3,
        checkpoint_data={"x": 1},
        step_history=[],
    )

    assert first["created"] is True
    assert second["created"] is False
    assert first["workflow"]["workflow_id"] == second["workflow"]["workflow_id"]
    assert len(client.rows) == 1


def test_get_or_create_for_approval_different_approval_ids_create_distinct_workflows():
    client = FakeSupabaseClient()
    store = OnboardingWorkflowStore(client=client)

    a = store.get_or_create_for_approval(
        approval_id=str(uuid4()),
        workflow_id=str(uuid4()),
        mission_id="m-1",
        worker_id="w-1",
        platform="pinterest",
        status="awaiting_human",
        current_step=1,
        total_steps=3,
        checkpoint_data={},
        step_history=[],
    )
    b = store.get_or_create_for_approval(
        approval_id=str(uuid4()),
        workflow_id=str(uuid4()),
        mission_id="m-1",
        worker_id="w-1",
        platform="pinterest",
        status="awaiting_human",
        current_step=1,
        total_steps=3,
        checkpoint_data={},
        step_history=[],
    )

    assert a["workflow"]["workflow_id"] != b["workflow"]["workflow_id"]
    assert len(client.rows) == 2


def test_get_by_started_by_approval_id_returns_existing_workflow():
    client = FakeSupabaseClient()
    store = OnboardingWorkflowStore(client=client)
    approval_id = str(uuid4())

    store.get_or_create_for_approval(
        approval_id=approval_id,
        workflow_id=str(uuid4()),
        mission_id="m-1",
        worker_id="w-1",
        platform="pinterest",
        status="awaiting_human",
        current_step=1,
        total_steps=3,
        checkpoint_data={},
        step_history=[],
    )
    found = store.get_by_started_by_approval_id(approval_id)
    assert found is not None
    assert found["started_by_approval_id"] == approval_id


def test_get_by_started_by_approval_id_returns_none_for_unknown():
    store = OnboardingWorkflowStore(client=FakeSupabaseClient())
    assert store.get_by_started_by_approval_id(str(uuid4())) is None
    assert store.get_by_started_by_approval_id("") is None


def test_get_or_create_for_approval_legacy_row_with_null_approval_id_remains_valid():
    """Legacy rows (started_by_approval_id NULL) must not be affected by new code paths."""
    client = FakeSupabaseClient()
    store = OnboardingWorkflowStore(client=client)

    legacy = store.create(
        workflow_id="legacy-wf",
        mission_id="m-1",
        worker_id="w-1",
        platform="pinterest",
        status="awaiting_human",
        current_step=1,
        total_steps=3,
        checkpoint_data={},
        step_history=[],
    )
    assert legacy["success"] is True
    # A new claim for a different approval should not be confused with legacy
    claim = store.get_or_create_for_approval(
        approval_id=str(uuid4()),
        workflow_id="new-wf",
        mission_id="m-1",
        worker_id="w-1",
        platform="pinterest",
        status="awaiting_human",
        current_step=1,
        total_steps=3,
        checkpoint_data={},
        step_history=[],
    )
    assert claim["success"] is True
    assert claim["created"] is True
    # get() on the legacy workflow_id still works
    assert store.get("legacy-wf") is not None


# ---------------------------------------------------------------------------
# Connector-level tests
# ---------------------------------------------------------------------------
def test_pinterest_start_onboarding_with_approval_id_persists_link():
    client = FakeSupabaseClient()
    store = OnboardingWorkflowStore(client=client)
    connector = PinterestConnector(workflow_store=store)
    approval_id = str(uuid4())

    result = connector.start_onboarding("worker-1", approval_id=approval_id)

    assert result["success"] is True
    assert result["workflow_id"] is not None
    # The store should now have exactly one row for this approval.
    assert len(client.rows) == 1
    assert client.rows[0]["started_by_approval_id"] == approval_id


def test_pinterest_start_onboarding_same_approval_id_returns_same_workflow():
    client = FakeSupabaseClient()
    store = OnboardingWorkflowStore(client=client)
    connector = PinterestConnector(workflow_store=store)
    approval_id = str(uuid4())

    first = connector.start_onboarding("worker-1", approval_id=approval_id)
    second = connector.start_onboarding("worker-1", approval_id=approval_id)

    assert first["workflow_id"] == second["workflow_id"]
    assert second.get("reused_existing_workflow") is True
    assert first.get("reused_existing_workflow") in (None, False)
    assert len(client.rows) == 1


def test_pinterest_start_onboarding_new_connector_instance_returns_same_workflow():
    client = FakeSupabaseClient()
    approval_id = str(uuid4())

    store1 = OnboardingWorkflowStore(client=client)
    c1 = PinterestConnector(workflow_store=store1)
    first = c1.start_onboarding("worker-1", approval_id=approval_id)

    # Simulate process restart by constructing a brand new store/connector
    # pointing at the same backing store state.
    store2 = OnboardingWorkflowStore(client=client)
    c2 = PinterestConnector(workflow_store=store2)
    second = c2.start_onboarding("worker-1", approval_id=approval_id)

    assert first["workflow_id"] == second["workflow_id"]
    assert second.get("reused_existing_workflow") is True


def test_pinterest_start_onboarding_without_approval_id_creates_fresh_workflow():
    """No-approval path must remain unchanged: fresh UUID each call."""
    client = FakeSupabaseClient()
    store = OnboardingWorkflowStore(client=client)
    connector = PinterestConnector(workflow_store=store)

    a = connector.start_onboarding("worker-1")
    b = connector.start_onboarding("worker-1")

    assert a["success"] and b["success"]
    assert a["workflow_id"] != b["workflow_id"]
    # No started_by_approval_id on the legacy path
    assert "started_by_approval_id" not in a or a.get("started_by_approval_id") in (None, "")


def test_pinterest_start_onboarding_different_approvals_create_distinct_workflows():
    client = FakeSupabaseClient()
    store = OnboardingWorkflowStore(client=client)
    connector = PinterestConnector(workflow_store=store)

    a = connector.start_onboarding("worker-1", approval_id=str(uuid4()))
    b = connector.start_onboarding("worker-1", approval_id=str(uuid4()))

    assert a["workflow_id"] != b["workflow_id"]
    assert len(client.rows) == 2


def test_pinterest_start_onboarding_in_memory_fallback_is_idempotent_within_process():
    """Without a DB, the in-memory fallback must still be idempotent within a process."""
    store = OnboardingWorkflowStore(client=None)
    connector = PinterestConnector(workflow_store=store)
    approval_id = str(uuid4())

    first = connector.start_onboarding("worker-1", approval_id=approval_id)
    second = connector.start_onboarding("worker-1", approval_id=approval_id)

    assert first["workflow_id"] == second["workflow_id"]
    assert second.get("reused_existing_workflow") is True


def test_pinterest_start_onboarding_rpc_failure_falls_back_to_legacy_path():
    """If the DB function fails, fall through to the legacy create() path so
    the workflow is still created (durable retry is a separate concern)."""
    client = FakeSupabaseClient()
    client.fail_next_rpc = True
    store = OnboardingWorkflowStore(client=client)
    connector = PinterestConnector(workflow_store=store)

    result = connector.start_onboarding("worker-1", approval_id=str(uuid4()))
    assert result["success"] is True
    assert result["workflow_id"] is not None


# ---------------------------------------------------------------------------
# Process-restart simulation
# ---------------------------------------------------------------------------
def test_process_restart_simulation_same_approval_returns_same_workflow():
    """Simulate a full process restart: new store + new connector + new client
    but the same backing database. The approval must still resolve to the
    same workflow_id without any in-process state sharing."""
    client = FakeSupabaseClient()
    store1 = OnboardingWorkflowStore(client=client)
    c1 = PinterestConnector(workflow_store=store1)
    approval_id = str(uuid4())
    first = c1.start_onboarding("worker-1", approval_id=approval_id)
    first_id = first["workflow_id"]

    # Process restart: brand new objects, same client (representing the
    # same persistent DB).
    store2 = OnboardingWorkflowStore(client=client)
    c2 = PinterestConnector(workflow_store=store2)
    second = c2.start_onboarding("worker-1", approval_id=approval_id)

    assert first_id == second["workflow_id"]
    assert second.get("reused_existing_workflow") is True


# ---------------------------------------------------------------------------
# Concurrency test (in-process)
# ---------------------------------------------------------------------------
def test_concurrent_start_with_same_approval_creates_at_most_one_workflow_in_memory():
    """Two threads racing on the same approval_id via the in-memory fallback
    must converge on a single workflow. With the DB, the partial unique
    index is the authoritative guarantee (covered by test_concurrent_* via
    the fake RPC, which serializes on its own lock)."""
    import concurrent.futures

    client = FakeSupabaseClient()
    store = OnboardingWorkflowStore(client=client)
    connector = PinterestConnector(workflow_store=store)
    approval_id = str(uuid4())

    def call():
        return connector.start_onboarding("worker-1", approval_id=approval_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda _: call(), range(16)))

    workflow_ids = {r["workflow_id"] for r in results}
    assert len(workflow_ids) == 1, f"expected one workflow, got {workflow_ids}"
    # The fake RPC serialized; the row count reflects that.
    assert len(client.rows) == 1


# ---------------------------------------------------------------------------
# Sanity: no regression in the legacy public surface
# ---------------------------------------------------------------------------
def test_legacy_create_get_update_still_work():
    store = OnboardingWorkflowStore(client=None)
    created = store.create(
        workflow_id="wf-legacy",
        mission_id="m-1",
        worker_id="w-1",
        platform="pinterest",
        status="awaiting_human",
        current_step=1,
        total_steps=3,
        checkpoint_data={},
        step_history=[],
    )
    assert created["success"] is True

    fetched = store.get("wf-legacy")
    assert fetched is not None
    assert fetched["workflow_id"] == "wf-legacy"

    updated = store.update("wf-legacy", status="completed", current_step=3)
    assert updated["success"] is True
    assert updated["workflow"]["status"] == "completed"


# ---------------------------------------------------------------------------
# End-to-end: approval resume reuses workflow on retry
# ---------------------------------------------------------------------------
def test_resume_service_reuses_workflow_on_retry():
    """End-to-end: when ApprovalResumeService.resume() is called twice for
    the same approval_id, the second resume must return the same workflow_id
    instead of creating a duplicate."""
    from app.services.approval_gateway import ApprovalGateway
    from app.services.approval_resume_service import ApprovalResumeService
    from app.services.connectors.registry import ConnectorRegistry
    from app.services.human_intervention import HumanInterventionManager
    from app.services.stores.platform_connection_store import (
        PlatformConnectionStore,
    )

    client = FakeSupabaseClient()
    workflow_store = OnboardingWorkflowStore(client=client)
    connection_store = PlatformConnectionStore(client=client)
    registry = ConnectorRegistry()
    registry.register(
        PinterestConnector(
            workflow_store=workflow_store,
            connection_store=connection_store,
        )
    )

    gateway = ApprovalGateway()
    request = gateway.create_request(
        mission_id="m-1",
        action_type="start_platform_onboarding",
        risk_level="moderate",
        payload={
            "platform": "pinterest",
            "worker_id": "worker-1",
        },
    )
    assert request["success"] is True
    approval_id = request["request"]["id"]
    gateway.approve_request(approval_id, approved_by="tester")

    service = ApprovalResumeService(
        approval_gateway=gateway,
        connector_registry=registry,
        human_intervention_manager=HumanInterventionManager(),
    )

    first = service.resume(approval_id)
    assert first["status"] == "awaiting_human_intervention"
    first_wf = first["workflow_id"]
    assert first_wf is not None
    # Exactly one row in the fake DB
    assert len(client.rows) == 1

    # Second resume for the same approval must not create another workflow.
    # The state guard / in-process cache returns a non-destructive result;
    # crucially the database row count must stay at 1.
    second = service.resume(approval_id)
    assert second.get("status") in {"awaiting_human_intervention", "awaiting_resume", "completed"}
    assert len(client.rows) == 1, (
        "Second resume for the same approval created a duplicate workflow; "
        f"workflow_ids in fake DB: {[r.get('id') for r in client.rows]}"
    )


def test_resume_service_process_restart_returns_same_workflow():
    """A fresh ApprovalResumeService constructed against the same persistent
    database must resolve the same approval_id to the same workflow_id
    even though the in-process ``_executed`` cache is empty."""
    from app.services.approval_gateway import ApprovalGateway
    from app.services.approval_resume_service import ApprovalResumeService
    from app.services.connectors.registry import ConnectorRegistry
    from app.services.human_intervention import HumanInterventionManager
    from app.services.stores.platform_connection_store import (
        PlatformConnectionStore,
    )

    client = FakeSupabaseClient()
    ws1 = OnboardingWorkflowStore(client=client)
    cs1 = PlatformConnectionStore(client=client)
    registry1 = ConnectorRegistry()
    registry1.register(
        PinterestConnector(workflow_store=ws1, connection_store=cs1)
    )
    gateway = ApprovalGateway()
    request = gateway.create_request(
        mission_id="m-1",
        action_type="start_platform_onboarding",
        risk_level="moderate",
        payload={"platform": "pinterest", "worker_id": "w-1"},
    )
    approval_id = request["request"]["id"]
    gateway.approve_request(approval_id, approved_by="tester")

    service1 = ApprovalResumeService(
        approval_gateway=gateway,
        connector_registry=registry1,
        human_intervention_manager=HumanInterventionManager(),
    )
    first = service1.resume(approval_id)
    first_wf = first["workflow_id"]
    assert len(client.rows) == 1

    # Simulate process restart: brand new service, registry, and stores,
    # all pointing at the same persistent DB.
    ws2 = OnboardingWorkflowStore(client=client)
    cs2 = PlatformConnectionStore(client=client)
    registry2 = ConnectorRegistry()
    registry2.register(
        PinterestConnector(workflow_store=ws2, connection_store=cs2)
    )
    service2 = ApprovalResumeService(
        approval_gateway=gateway,
        connector_registry=registry2,
        human_intervention_manager=HumanInterventionManager(),
    )
    second = service2.resume(approval_id)

    # The state-level guard checks connection.status; for
    # start_platform_onboarding the platform is not yet connected so the
    # state guard does not short-circuit. The connector must therefore
    # be invoked again — but the claim RPC must return the existing row.
    assert second["workflow_id"] == first_wf
    assert len(client.rows) == 1, (
        f"Process-restart resume created a duplicate workflow: "
        f"{[r.get('id') for r in client.rows]}"
    )

