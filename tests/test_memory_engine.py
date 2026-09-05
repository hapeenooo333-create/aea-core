from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.memory_engine import AtlasMemoryEngine


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, client, table_name: str):
        self._client = client
        self._table_name = table_name
        self._filters: list[tuple[str, object]] = []
        self._order: tuple[str, bool] | None = None
        self._limit: int | None = None
        self._operation: str | None = None
        self._payload: dict | None = None

    def insert(self, payload: dict):
        self._operation = "insert"
        self._payload = payload
        return self

    def select(self, *_args, **_kwargs):
        self._operation = "select"
        return self

    def eq(self, column: str, value: object):
        self._filters.append((column, value))
        return self

    def order(self, column: str, desc: bool = False):
        self._order = (column, desc)
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def delete(self):
        self._operation = "delete"
        return self

    def execute(self):
        if self._operation == "insert":
            assert self._table_name == "agent_memory_entries"
            row = {
                "id": "entry-1",
                "worker_id": self._payload["worker_id"],
                "mission_id": self._payload.get("mission_id"),
                "memory_type": self._payload["memory_type"],
                "content": self._payload.get("content") or {},
                "metadata": self._payload.get("metadata", {}),
                "importance_score": self._payload.get("importance_score", 0.5),
                "created_at": "2024-01-01T00:00:00Z",
            }
            self._client.rows.append(row)
            return FakeResponse([row])

        if self._operation == "select":
            rows = list(self._client.rows)
            if self._filters:
                column, value = self._filters[0]
                rows = [row for row in rows if row.get(column) == value]
            if self._order:
                rows = sorted(rows, key=lambda item: item.get(self._order[0], ""), reverse=self._order[1])
            if self._limit is not None:
                rows = rows[: self._limit]
            return FakeResponse(rows)

        if self._operation == "delete":
            memory_id = self._filters[0][1] if self._filters else None
            if memory_id is not None:
                self._client.rows = [row for row in self._client.rows if row.get("id") != memory_id]
            return FakeResponse([{"id": memory_id}])

        return FakeResponse([])


class FakeSupabaseClient:
    def __init__(self):
        self.rows: list[dict] = []
        self.table_name: str | None = None

    def table(self, table_name: str):
        self.table_name = table_name
        return FakeQuery(self, table_name)


def test_store_memory_uses_agent_memory_entries_and_defaults():
    client = FakeSupabaseClient()
    engine = AtlasMemoryEngine()
    engine._client = client

    response = engine.store_memory(
        "worker-1",
        "note",
        {"mission_id": "mission-7", "text": "hello"},
    )

    assert response["success"] is True
    assert client.table_name == "agent_memory_entries"
    assert client.rows[0]["mission_id"] == "mission-7"
    assert client.rows[0]["metadata"] == {}
    assert client.rows[0]["importance_score"] == 0.5
    assert response["memory"]["content"]["text"] == "hello"
    assert response["memory"]["worker_id"] == "worker-1"


def test_get_recent_memories_returns_backward_compatible_shape():
    client = FakeSupabaseClient()
    client.rows = [
        {
            "id": "entry-2",
            "worker_id": "worker-1",
            "mission_id": "mission-9",
            "memory_type": "summary",
            "content": {"text": "hello"},
            "metadata": {"source": "unit-test"},
            "importance_score": 0.8,
            "created_at": "2024-01-01T00:00:00Z",
        }
    ]
    engine = AtlasMemoryEngine()
    engine._client = client

    memories = engine.get_recent_memories("worker-1", limit=5)

    assert len(memories) == 1
    assert memories[0]["id"] == "entry-2"
    assert memories[0]["content"]["text"] == "hello"
    assert memories[0]["mission_id"] == "mission-9"
    assert memories[0]["metadata"] == {"source": "unit-test"}
    assert memories[0]["importance_score"] == 0.8


def test_delete_memory_uses_agent_memory_entries_table():
    client = FakeSupabaseClient()
    client.rows = [{"id": "entry-3", "worker_id": "worker-1"}]
    engine = AtlasMemoryEngine()
    engine._client = client

    result = engine.delete_memory("entry-3")

    assert result["success"] is True
    assert client.table_name == "agent_memory_entries"
    assert client.rows == []
