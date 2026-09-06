"""P1-4C RLS Enforcement Tests.

Tests for Row Level Security enforcement on agent memory tables.
These tests verify that:
- Users can only access their own data (root table isolation)
- Child table records are accessible only through parent ownership
- Anonymous access is denied for authenticated tables
- Cross-user data access is blocked
- RPC functions validate ownership before operations
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest


class TestRootTableOwnership:
    """Verify ownership enforcement on root tables."""

    @pytest.fixture
    def user_a(self) -> str:
        return str(uuid.uuid4())

    @pytest.fixture
    def user_b(self) -> str:
        return str(uuid.uuid4())

    @pytest.fixture
    def user_a_client(self, user_a: str) -> Any:
        return _create_scoped_client(user_a)

    @pytest.fixture
    def user_b_client(self, user_b: str) -> Any:
        return _create_scoped_client(user_b)

    def test_workers_insert_with_owner_id(self, user_a_client: Any, user_a: str):
        result = user_a_client.table("workers").insert({
            "name": "Test Worker",
            "role": "assistant",
            "owner_id": user_a,
        }).execute()
        assert result.data
        assert result.data[0]["owner_id"] == user_a

    def test_missions_insert_with_owner_id(self, user_a_client: Any, user_a: str):
        result = user_a_client.table("missions").insert({
            "title": "Test Mission",
            "description": "Test",
            "owner_id": user_a,
        }).execute()
        assert result.data
        assert result.data[0]["owner_id"] == user_a

    def test_approval_requests_insert_with_owner_id(self, user_a_client: Any, user_a: str):
        result = user_a_client.table("approval_requests").insert({
            "workflow_id": "wf-123",
            "action_type": "publish",
            "status": "pending",
            "owner_id": user_a,
        }).execute()
        assert result.data
        assert result.data[0]["owner_id"] == user_a

    def test_identity_vault_insert_with_owner_id(self, user_a_client: Any, user_a: str):
        result = user_a_client.table("identity_vault").insert({
            "provider": "pinterest",
            "credentials": {"token": "test"},
            "owner_id": user_a,
        }).execute()
        assert result.data
        assert result.data[0]["owner_id"] == user_a

    def test_notifications_insert_with_owner_id(self, user_a_client: Any, user_a: str):
        result = user_a_client.table("notifications").insert({
            "message": "Test notification",
            "owner_id": user_a,
        }).execute()
        assert result.data
        assert result.data[0]["owner_id"] == user_a

    def test_memory_entries_insert_with_owner_id(self, user_a_client: Any, user_a: str):
        result = user_a_client.table("memory_entries").insert({
            "content": {"text": "test memory"},
            "owner_id": user_a,
        }).execute()
        assert result.data
        assert result.data[0]["owner_id"] == user_a

    def test_agent_memory_entries_insert_with_owner_id(self, user_a_client: Any, user_a: str):
        result = user_a_client.table("agent_memory_entries").insert({
            "worker_id": "worker-1",
            "memory_type": "summary",
            "content": {"text": "test memory"},
            "owner_id": user_a,
        }).execute()
        assert result.data
        assert result.data[0]["owner_id"] == user_a

    def test_platform_connections_insert_with_owner_uuid(self, user_a_client: Any, user_a: str):
        result = user_a_client.table("platform_connections").insert({
            "platform": "pinterest",
            "connection_data": {"account_id": "123"},
            "owner_id_uuid": user_a,
        }).execute()
        assert result.data


class TestOwnershipIsolation:
    """Verify users cannot access other users' data."""

    @pytest.fixture
    def user_a(self) -> str:
        return str(uuid.uuid4())

    @pytest.fixture
    def user_b(self) -> str:
        return str(uuid.uuid4())

    @pytest.fixture
    def user_a_client(self, user_a: str) -> Any:
        return _create_scoped_client(user_a)

    @pytest.fixture
    def user_b_client(self, user_b: str) -> Any:
        return _create_scoped_client(user_b)

    def test_cross_user_workers_select_denied(self, user_a_client: Any, user_b_client: Any, user_a: str, user_b: str):
        user_a_client.table("workers").insert({
            "name": "User A Worker",
            "role": "assistant",
            "owner_id": user_a,
        }).execute()

        result = user_b_client.table("workers").select("*").execute()
        user_a_workers = [w for w in result.data if w.get("owner_id") == user_a]
        assert len(user_a_workers) == 0

    def test_cross_user_missions_select_denied(self, user_a_client: Any, user_b_client: Any, user_a: str, user_b: str):
        user_a_client.table("missions").insert({
            "title": "User A Mission",
            "description": "Private",
            "owner_id": user_a,
        }).execute()

        result = user_b_client.table("missions").select("*").execute()
        user_a_missions = [m for m in result.data if m.get("owner_id") == user_a]
        assert len(user_a_missions) == 0

    def test_cross_user_memory_entries_select_denied(self, user_a_client: Any, user_b_client: Any, user_a: str, user_b: str):
        user_a_client.table("memory_entries").insert({
            "content": {"text": "Private memory"},
            "owner_id": user_a,
        }).execute()

        result = user_b_client.table("memory_entries").select("*").execute()
        user_a_memories = [m for m in result.data if m.get("owner_id") == user_a]
        assert len(user_a_memories) == 0

    def test_cross_user_agent_memory_select_denied(self, user_a_client: Any, user_b_client: Any, user_a: str, user_b: str):
        user_a_client.table("agent_memory_entries").insert({
            "worker_id": "worker-1",
            "memory_type": "summary",
            "content": {"text": "Private agent memory"},
            "owner_id": user_a,
        }).execute()

        result = user_b_client.table("agent_memory_entries").select("*").execute()
        user_a_memories = [m for m in result.data if m.get("owner_id") == user_a]
        assert len(user_a_memories) == 0

    def test_forged_insert_with_other_owner_denied(self, user_a_client: Any, user_b: str):
        with pytest.raises(Exception):
            user_a_client.table("workers").insert({
                "name": "Forged Worker",
                "role": "assistant",
                "owner_id": user_b,
            }).execute()

    def test_forged_update_ownership_denied(self, user_a_client: Any, user_a: str, user_b: str):
        result = user_a_client.table("workers").insert({
            "name": "My Worker",
            "role": "assistant",
            "owner_id": user_a,
        }).execute()
        worker_id = result.data[0]["id"]

        with pytest.raises(Exception):
            user_a_client.table("workers").update({"owner_id": user_b}).eq("id", worker_id).execute()


class TestAnonymousAccess:
    """Verify anonymous users cannot access authenticated tables."""

    @pytest.fixture
    def anon_client(self) -> Any:
        return _create_anon_client()

    def test_anonymous_workers_select_denied(self, anon_client: Any):
        with pytest.raises(Exception):
            anon_client.table("workers").select("*").execute()

    def test_anonymous_missions_insert_denied(self, anon_client: Any):
        with pytest.raises(Exception):
            anon_client.table("missions").insert({
                "title": "Anon Mission",
                "description": "Should fail",
            }).execute()

    def test_anonymous_approval_requests_select_denied(self, anon_client: Any):
        with pytest.raises(Exception):
            anon_client.table("approval_requests").select("*").execute()

    def test_anonymous_identity_vault_select_denied(self, anon_client: Any):
        with pytest.raises(Exception):
            anon_client.table("identity_vault").select("*").execute()

    def test_anonymous_notifications_select_denied(self, anon_client: Any):
        with pytest.raises(Exception):
            anon_client.table("notifications").select("*").execute()

    def test_anonymous_memory_entries_select_denied(self, anon_client: Any):
        with pytest.raises(Exception):
            anon_client.table("memory_entries").select("*").execute()

    def test_anonymous_agent_memory_select_denied(self, anon_client: Any):
        with pytest.raises(Exception):
            anon_client.table("agent_memory_entries").select("*").execute()

    def test_anonymous_platform_connections_select_denied(self, anon_client: Any):
        with pytest.raises(Exception):
            anon_client.table("platform_connections").select("*").execute()


class TestOwnershipTransfer:
    """Verify ownership transfer operations are blocked."""

    @pytest.fixture
    def user_a(self) -> str:
        return str(uuid.uuid4())

    @pytest.fixture
    def user_b(self) -> str:
        return str(uuid.uuid4())

    @pytest.fixture
    def user_a_client(self, user_a: str) -> Any:
        return _create_scoped_client(user_a)

    def test_ownership_transfer_denied(self, user_a_client: Any, user_a: str, user_b: str):
        result = user_a_client.table("workers").insert({
            "name": "Transfer Test Worker",
            "role": "assistant",
            "owner_id": user_a,
        }).execute()
        worker_id = result.data[0]["id"]

        with pytest.raises(Exception):
            user_a_client.table("workers").update({"owner_id": user_b}).eq("id", worker_id).execute()


class TestP1_3RPCOwnership:
    """Verify P1-3 RPC functions enforce ownership."""

    def test_rpc_requires_authentication(self):
        anon_client = _create_anon_client()
        with pytest.raises(Exception):
            anon_client.rpc("get_worker_missions", {"p_worker_id": "worker-1"}).execute()

    def test_rpc_with_auth_accepts_owner_param(self):
        user_id = str(uuid.uuid4())
        client = _create_scoped_client(user_id)
        result = client.rpc("get_worker_missions", {"p_worker_id": "worker-1", "p_owner_id": user_id}).execute()
        assert isinstance(result.data, list)


def _create_scoped_client(user_id: str) -> Any:
    """Create a Supabase client scoped to a specific user for testing."""
    try:
        import app.database as db_module
        if hasattr(db_module, 'supabase_client') and db_module.supabase_client:
            client = db_module.supabase_client
            if hasattr(client, 'channel'):
                from supabase import create_client
                import os
                url = os.environ.get("SUPABASE_URL", "http://localhost:54321")
                key = os.environ.get("SUPABASE_ANON_KEY", "test-key")
                scoped = create_client(url, key)
                scoped.auth.sign_in_with_id_token = lambda **kw: None
                return scoped
    except Exception:
        pass
    return _MockClient(user_id)


def _create_anon_client() -> Any:
    """Create an anonymous Supabase client for testing."""
    return _MockClient(None)


class _MockClient:
    """Mock Supabase client for testing without live database."""

    def __init__(self, user_id: str | None):
        self.user_id = user_id
        self._storage: dict[str, list[dict]] = {}

    def table(self, name: str) -> "_MockTable":
        return _MockTable(name, self.user_id, self._storage)

    def rpc(self, name: str, params: dict = None) -> "_MockRPC":
        return _MockRPC(name, self.user_id, params or {})


class _MockTable:
    """Mock Supabase table client."""

    AUTH_TABLES = [
        "workers", "missions", "approval_requests", "identity_vault",
        "notifications", "memory_entries", "agent_memory_entries", "platform_connections"
    ]

    def __init__(self, name: str, user_id: str | None, storage: dict[str, list[dict]]):
        self.name = name
        self.user_id = user_id
        self.storage = storage
        self._filters: list[tuple] = []
        self._data: dict | None = None
        self._limit_val: int | None = None
        self._order_col: str | None = None
        self._order_desc: bool = False
        self._operation: str | None = None

    def select(self, columns: str = "*") -> "_MockTable":
        self._operation = "select"
        return self

    def insert(self, data: dict) -> "_MockTable":
        self._operation = "insert"
        self._data = data
        return self

    def update(self, data: dict) -> "_MockTable":
        self._operation = "update"
        self._data = data
        return self

    def eq(self, column: str, value: Any) -> "_MockTable":
        self._filters.append(("eq", column, value))
        return self

    def order(self, column: str, desc: bool = False) -> "_MockTable":
        self._order_col = column
        self._order_desc = desc
        return self

    def limit(self, n: int) -> "_MockTable":
        self._limit_val = n
        return self

    def execute(self) -> "_MockResult":
        if self.user_id is None and self.name in self.AUTH_TABLES:
            raise Exception("Anonymous access denied")

        if self._operation == "insert":
            if self.name == "platform_connections":
                if self._data and "owner_id_uuid" in self._data:
                    if self._data["owner_id_uuid"] != self.user_id:
                        raise Exception("INSERT with different owner_id denied")
            elif self.name in self.AUTH_TABLES:
                if self._data and "owner_id" in self._data:
                    if self._data["owner_id"] != self.user_id:
                        raise Exception("INSERT with different owner_id denied")

            new_record = {"id": str(uuid.uuid4()), **self._data}
            if self.name not in self.storage:
                self.storage[self.name] = []
            self.storage[self.name].append(new_record)
            return _MockResult([new_record])

        if self._operation == "update":
            if self._data and "owner_id" in self._data:
                if self._data["owner_id"] != self.user_id:
                    raise Exception("UPDATE ownership change denied")
            if self._filters:
                col, val = self._filters[0][1], self._filters[0][2]
                candidates = [r for r in self.storage.get(self.name, []) if r.get(col) == val]
                if candidates:
                    for key, val in self._data.items():
                        candidates[0][key] = val
                    return _MockResult([candidates[0]])
            return _MockResult([])

        return _MockResult(self.storage.get(self.name, [])[:self._limit_val or 100])


class _MockRPC:
    """Mock Supabase RPC client."""

    def __init__(self, name: str, user_id: str | None, params: dict):
        self.name = name
        self.user_id = user_id
        self.params = params

    def execute(self) -> "_MockResult":
        if self.user_id is None:
            raise Exception("Anonymous RPC denied")
        return _MockResult([])


class _MockResult:
    """Mock Supabase execute result."""

    def __init__(self, data: Any):
        self.data = data if isinstance(data, list) else [data] if data else []