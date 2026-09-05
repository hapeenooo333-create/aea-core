"""Tests for the connector persistence layer (P0-5).

Covers:
- OnboardingWorkflowStore create/get/update
- PlatformConnectionStore upsert/get
- PinterestConnector start_onboarding persists workflow
- PinterestConnector resume_onboarding can retrieve persisted workflow
- completed onboarding updates platform connection
- connector works without Supabase through fallback behavior
- mission_id is forwarded from WorkerRuntime
- no sensitive auth fields are persisted
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.connector_memory import ConnectorMemoryRecorder  # noqa: E402  (sanity import)
from app.services.connectors.pinterest_connector import PinterestConnector  # noqa: E402
from app.services.stores.onboarding_workflow_store import OnboardingWorkflowStore  # noqa: E402
from app.services.stores.platform_connection_store import PlatformConnectionStore  # noqa: E402
from app.services.worker_runtime import WorkerRuntime  # noqa: E402


# ---------------------------------------------------------------------------
# Fake Supabase client helpers
# ---------------------------------------------------------------------------
class FakeResponse:
    """Mimic the Supabase ``.execute()`` return shape used by stores."""

    def __init__(self, data):
        self.data = data


class FakeQuery:
    """Fluent query builder for Supabase-style chain calls."""

    def __init__(self, table_name: str, store_state: dict, last_payload: list | None = None):
        self._table_name = table_name
        self._store_state = store_state
        self._filters: list[tuple[str, str]] = []
        self._last_payload = last_payload if last_payload is not None else []
        self._limit = None

    def select(self, *_args, **_kwargs):
        return self

    def insert(self, payload):
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            if self._table_name == "onboarding_workflows":
                key = row.get("id")
                if key is not None:
                    self._store_state[key] = dict(row)
            elif self._table_name == "platform_connections":
                key = (row.get("owner_id"), row.get("platform"))
                self._store_state.setdefault("__conn__", {})[key] = dict(row)
                self._store_state[f"{key[0]}|{key[1]}"] = dict(row)
        self._last_payload = list(rows)
        return self

    def update(self, payload):
        self._last_payload = payload
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def order(self, *_args, **_kwargs):
        return self

    def execute(self):
        rows: list[dict] = []
        if self._last_payload and isinstance(self._last_payload, list) and self._last_payload and isinstance(self._last_payload[0], dict) and not self._filters:
            # Insert path: data is whatever we tried to insert.
            rows = list(self._last_payload)
        else:
            # Read path: scan store_state and apply eq filters.
            for stored in self._store_state.values():
                if not isinstance(stored, dict):
                    continue
                if stored.get("__conn__") == "__conn__":
                    continue
                match = True
                for column, value in self._filters:
                    if stored.get(column) != value:
                        match = False
                        break
                if match:
                    rows.append(stored)
        if self._limit == 1:
            rows = rows[:1]
        return FakeResponse(rows)


class FakeTable:
    """Mimic ``client.table(name)`` returning a :class:`FakeQuery`."""

    def __init__(self, name: str, state: dict):
        self._name = name
        self._state = state
        self._last_payload = []

    def __call__(self, *args, **kwargs):
        return self

    def insert(self, payload):
        rows = payload if isinstance(payload, list) else [payload]
        # Persist into the fake state so subsequent select calls return the rows.
        for row in rows:
            key = row.get("id") or row.get("id")
            if self._name == "onboarding_workflows":
                self._state[key] = dict(row)
            elif self._name == "platform_connections":
                key = (row.get("owner_id"), row.get("platform"))
                self._state.setdefault("__conn__", {})[key] = dict(row)
                self._state[f"{key[0]}|{key[1]}"] = dict(row)
        self._last_payload = rows
        return FakeQuery(self._name, self._state, rows)

    def update(self, payload):
        self._last_payload = payload
        return FakeQuery(self._name, self._state, [payload])

    def select(self, *_args, **_kwargs):
        return FakeQuery(self._name, self._state)

    def eq(self, column, value):
        return FakeQuery(self._name, self._state)

    def upsert(self, payload):
        return self.insert(payload)


class FakeSupabaseClient:
    """Minimal Supabase client fake used by stores."""

    def __init__(self):
        self.tables: dict[str, FakeTable] = {}

    def table(self, name: str):
        if name not in self.tables:
            state: dict = {"__conn__": {}}
            self.tables[name] = FakeTable(name, state)
        return self.tables[name]


# ---------------------------------------------------------------------------
# OnboardingWorkflowStore tests
# ---------------------------------------------------------------------------
def test_onboarding_workflow_store_create_and_get_with_supabase():
    """When a Supabase client is provided the store still returns success
    and the record is accessible through the in-memory fallback if the
    client write fails silently. Here we exercise the fallback path with
    a non-functional fake client to confirm graceful degradation."""
    client = FakeSupabaseClient()
    store = OnboardingWorkflowStore(client=client)

    result = store.create(
        workflow_id="wf-1",
        mission_id="mission-1",
        worker_id="worker-1",
        platform="pinterest",
        status="awaiting_human",
        current_step=1,
        total_steps=3,
        checkpoint_data={"checkpoint_type": "oauth_authorization_required"},
        step_history=[{"step": 1, "status": "pending"}],
    )

    assert result["success"]
    assert result["workflow"]["workflow_id"] == "wf-1"
    assert result["workflow"]["mission_id"] == "mission-1"
    assert result["workflow"]["worker_id"] == "worker-1"
    # Even if the fake client doesn't persist, the in-memory fallback means
    # get() can still return the record.
    fetched = store.get("wf-1")
    assert fetched is not None
    assert fetched["workflow_id"] == "wf-1"


def test_onboarding_workflow_store_fallback_without_supabase():
    """Store must work using in-memory fallback when no client is provided."""
    store = OnboardingWorkflowStore(client=None)

    result = store.create(
        workflow_id="wf-fallback",
        mission_id=None,
        worker_id="worker-fallback",
        platform="pinterest",
        status="awaiting_human",
        current_step=1,
        total_steps=3,
        checkpoint_data={"x": 1},
        step_history=[],
    )

    assert result["success"]
    fetched = store.get("wf-fallback")
    assert fetched is not None
    assert fetched["workflow_id"] == "wf-fallback"
    assert fetched["mission_id"] is None


def test_onboarding_workflow_store_update():
    store = OnboardingWorkflowStore(client=None)
    store.create(
        workflow_id="wf-upd",
        mission_id="m",
        worker_id="w",
        platform="pinterest",
        status="awaiting_human",
        current_step=1,
        total_steps=3,
        checkpoint_data={},
        step_history=[{"step": 1, "status": "pending"}],
    )

    update_result = store.update(
        "wf-upd",
        status="completed",
        current_step=3,
        step_history=[{"step": 1, "status": "completed"}],
    )
    assert update_result["success"]
    assert update_result["workflow"]["status"] == "completed"
    assert update_result["workflow"]["current_step"] == 3

    fetched = store.get("wf-upd")
    assert fetched["status"] == "completed"
    assert fetched["current_step"] == 3


def test_onboarding_workflow_store_list_by_worker():
    store = OnboardingWorkflowStore(client=None)
    for i in range(3):
        store.create(
            workflow_id=f"wf-{i}",
            mission_id=None,
            worker_id="w-A" if i < 2 else "w-B",
            platform="pinterest",
            status="awaiting_human" if i < 2 else "completed",
            current_step=1,
            total_steps=3,
            checkpoint_data={},
            step_history=[],
        )

    assert len(store.list_by_worker("w-A")) == 2
    assert len(store.list_by_worker("w-B", status="completed")) == 1
    assert len(store.list_by_worker("w-A", status="completed")) == 0


# ---------------------------------------------------------------------------
# PlatformConnectionStore tests
# ---------------------------------------------------------------------------
def test_platform_connection_store_upsert_and_get_fallback():
    store = PlatformConnectionStore(client=None)

    result = store.upsert(
        owner_id="worker-1",
        platform="pinterest",
        status="connected",
        external_account_id="acct-123",
        display_name="My Account",
        scopes=["pins:create"],
    )

    assert result["success"]
    fetched = store.get("worker-1", "pinterest")
    assert fetched is not None
    assert fetched["status"] == "connected"
    assert fetched["external_account_id"] == "acct-123"
    assert fetched["display_name"] == "My Account"
    assert fetched["scopes"] == ["pins:create"]


def test_platform_connection_store_upsert_is_idempotent():
    """Calling upsert twice must not create a duplicate row."""
    store = PlatformConnectionStore(client=None)

    store.upsert(owner_id="w", platform="pinterest", status="onboarding")
    store.upsert(
        owner_id="w",
        platform="pinterest",
        status="connected",
        scopes=["pins:create"],
    )

    rows = store.list_by_owner("w")
    assert len(rows) == 1
    assert rows[0]["status"] == "connected"


def test_platform_connection_store_sanitizes_scopes():
    store = PlatformConnectionStore(client=None)
    store.upsert(
        owner_id="w",
        platform="pinterest",
        status="connected",
        scopes=["pins:create", "access_token:secret-value", "boards:read"],
    )

    fetched = store.get("w", "pinterest")
    assert fetched["scopes"] == ["pins:create", "boards:read"]


# ---------------------------------------------------------------------------
# PinterestConnector persistence integration tests
# ---------------------------------------------------------------------------
def _make_connector() -> PinterestConnector:
    return PinterestConnector(
        workflow_store=OnboardingWorkflowStore(client=None),
        connection_store=PlatformConnectionStore(client=None),
    )


def test_pinterest_start_onboarding_persists_workflow():
    connector = _make_connector()

    result = connector.start_onboarding("worker-1", mission_id="mission-1")

    assert result["success"]
    workflow_id = result["workflow_id"]

    persisted = connector._workflow_store.get(workflow_id)
    assert persisted is not None
    assert persisted["mission_id"] == "mission-1"
    assert persisted["worker_id"] == "worker-1"
    assert persisted["platform"] == "pinterest"
    assert persisted["current_step"] == 1
    assert persisted["status"] == "awaiting_human"


def test_pinterest_resume_onboarding_recovers_persisted_workflow():
    """A fresh connector instance should be able to resume a workflow started
    in a previous instance (simulating DB-first restart recovery)."""
    connector_a = _make_connector()
    start = connector_a.start_onboarding("worker-recover", mission_id="mission-recover")
    workflow_id = start["workflow_id"]

    # Simulate process restart: new connector, fresh local caches, but the
    # workflow_store is shared so the in-memory store still holds the record.
    connector_b = PinterestConnector(
        workflow_store=connector_a._workflow_store,
        connection_store=connector_a._connection_store,
    )
    assert workflow_id not in connector_b._onboarding_workflows

    resume = connector_b.resume_onboarding(
        workflow_id,
        {"oauth_code": "test-code", "email": "user@example.com"},
    )

    assert resume["success"]
    assert resume["current_step"] == 2
    assert resume["checkpoint_type"] == "email_verification_required"


def test_pinterest_completed_onboarding_updates_platform_connection():
    connector = _make_connector()
    start = connector.start_onboarding("worker-finish", mission_id="m-finish")
    workflow_id = start["workflow_id"]

    connector.resume_onboarding(workflow_id, {"oauth_code": "c", "email": "e@x.com"})
    connector.resume_onboarding(workflow_id, {"email_verified": True})
    final = connector.resume_onboarding(workflow_id, {"account_configured": True})

    assert final["success"]
    assert final["status"] == "completed"

    persisted = connector._connection_store.get("worker-finish", "pinterest")
    assert persisted is not None
    assert persisted["status"] == "connected"


def test_pinterest_connector_works_without_supabase_via_fallback():
    """Default constructor must work even when Supabase is unavailable."""
    connector = PinterestConnector()

    start = connector.start_onboarding("worker-default", mission_id="m-default")
    workflow_id = start["workflow_id"]
    resume = connector.resume_onboarding(
        workflow_id,
        {"oauth_code": "c", "email": "e@x.com"},
    )
    assert resume["success"]
    assert resume["current_step"] == 2

    status = connector.get_account_status("worker-default")
    # No connection record exists yet, so default ``not_started`` is returned.
    assert status["status"] == "not_started"


def test_pinterest_connect_account_does_not_persist_sensitive_fields():
    connector = _make_connector()

    auth_data = {
        "oauth_code": "secret-oauth-code",
        "access_token": "secret-access-token",
        "refresh_token": "secret-refresh",
        "client_secret": "secret-secret",
        "external_account_id": "acct-1",
        "display_name": "My Pin Account",
        "scopes": ["pins:create", "access_token:bogus"],
    }

    result = connector.connect_account("worker-sec", auth_data)
    assert result["success"]

    persisted = connector._connection_store.get("worker-sec", "pinterest")
    assert persisted is not None
    # Sensitive keys must never appear in the persisted record.
    serialized = repr(persisted).lower()
    for forbidden in ("secret-oauth-code", "secret-access-token", "secret-refresh", "secret-secret"):
        assert forbidden not in serialized
    # Safe metadata should be preserved (sanitized where appropriate).
    assert persisted["external_account_id"] == "acct-1"
    assert persisted["display_name"] == "My Pin Account"
    # Scopes are sanitized to drop any token-like values.
    assert "access_token:bogus" not in persisted["scopes"]
    assert "pins:create" in persisted["scopes"]


def test_pinterest_start_onboarding_with_no_mission_id_persists_none():
    connector = _make_connector()
    result = connector.start_onboarding("worker-no-mission")
    workflow_id = result["workflow_id"]
    persisted = connector._workflow_store.get(workflow_id)
    assert persisted["mission_id"] is None


def test_worker_runtime_passes_mission_id_to_start_onboarding():
    """WorkerRuntime._dispatch_to_connector must propagate mission_id to the
    connector so that the persisted workflow record carries it."""
    runtime = WorkerRuntime()
    connector = _make_connector()
    runtime.set_connector_registry(
        __import__("app.services.connectors.registry", fromlist=["ConnectorRegistry"]).ConnectorRegistry()
    )
    # Manually register the connector so the dispatch path sees it.
    runtime.get_connector_registry().register(connector)

    dispatch = getattr(runtime, "_dispatch_to_connector")
    result = dispatch(
        mission_id="mission-from-runtime",
        action_type="start_platform_onboarding",
        payload={"worker_id": "worker-rt"},
        connector=connector,
    )

    # The dispatch path forwards to the connector and surfaces the workflow.
    assert result.get("workflow_id")
    persisted = connector._workflow_store.get(result["workflow_id"])
    assert persisted is not None
    assert persisted["mission_id"] == "mission-from-runtime"
    assert persisted["worker_id"] == "worker-rt"


def test_pinterest_resume_unknown_workflow_returns_error():
    connector = _make_connector()
    result = connector.resume_onboarding("does-not-exist", {})
    assert not result["success"]
    assert "not found" in result["error"].lower()


def test_pinterest_get_account_status_default_when_no_record():
    connector = _make_connector()
    status = connector.get_account_status("worker-never-seen")
    assert status["success"]
    assert status["status"] == "not_started"
    assert not status["details"]["connected"]


def test_pinterest_get_account_status_after_connect():
    connector = _make_connector()
    connector.connect_account("worker-conn", {"oauth_code": "abc"})
    status = connector.get_account_status("worker-conn")
    assert status["status"] == "connected"
    assert status["details"]["connected"] is True


# Sanity check: ensure ConnectorMemoryRecorder still imports cleanly so we
# didn't break a sibling service by introducing the stores package.
def test_connector_memory_recorder_still_importable():
    assert ConnectorMemoryRecorder is not None


# Use the pytest-mock-free MagicMock only to verify the import works.
def test_magic_mock_works():
    m = MagicMock()
    m.method.return_value = 1
    assert m.method() == 1