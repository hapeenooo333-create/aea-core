from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import app.main as main_module
import app.routers.atlas as atlas_module


class FakeResponse:
    def __init__(self, data: list[dict] | None = None):
        self.data = data or []


class FakeTable:
    def __init__(self, client: "FakeSupabaseClient", table_name: str):
        self.client = client
        self.table_name = table_name
        self._payload: dict | None = None
        self._method = "select"
        self._order_column: str | None = None
        self._order_desc = False
        self._filter_column: str | None = None
        self._filter_value: str | None = None

    def select(self, *_args, **_kwargs):
        self._method = "select"
        return self

    def insert(self, payload: dict):
        self._method = "insert"
        self._payload = payload
        return self

    def update(self, payload: dict):
        self._method = "update"
        self._payload = payload
        return self

    def eq(self, column: str, value):
        self._filter_column = column
        self._filter_value = value
        return self

    def order(self, column: str, desc: bool = False):
        self._order_column = column
        self._order_desc = desc
        return self

    def execute(self):
        if self._method == "insert":
            row = dict(self._payload or {})
            row.setdefault("id", str(len(self.client.data[self.table_name]) + 1))
            row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            if self.table_name == "missions":
                row.setdefault("status", "pending")
                row.setdefault("progress", 0)
                row.setdefault("updated_at", row["created_at"])
            self.client.data[self.table_name].append(row)
            return FakeResponse([row])

        if self._method == "update":
            rows = [dict(item) for item in self.client.data[self.table_name]]
            for row in rows:
                if str(row.get(self._filter_column or "")) == str(self._filter_value or ""):
                    row.update(self._payload or {})
                    row.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
            return FakeResponse(rows)

        rows = [dict(item) for item in self.client.data[self.table_name]]
        if self._order_column:
            rows.sort(key=lambda item: item.get(self._order_column, ""), reverse=self._order_desc)
        return FakeResponse(rows)


class FakeSupabaseClient:
    def __init__(self):
        self.data: dict[str, list[dict]] = {
            "missions": [],
            "mission_steps": [],
            "atlas_commands": [],
            "worker_responses": [],
        }

    def table(self, table_name: str) -> FakeTable:
        return FakeTable(self, table_name)


def test_atlas_mission_flow(monkeypatch):
    fake_client = FakeSupabaseClient()
    monkeypatch.setattr(atlas_module.database_module, "supabase_client", fake_client)

    with TestClient(main_module.app) as client:
        response = client.post(
            "/atlas/mission",
            json={
                "title": "Growth campaign",
                "description": "Launch an affiliate campaign for Pinterest traffic",
                "assigned_worker": "worker-1",
                "priority": "high",
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["mission_id"] is not None
        assert body["title"] == "Growth campaign"
        assert body["priority"] == "high"

        missions_response = client.get("/atlas/missions")
        assert missions_response.status_code == 200, missions_response.text
        assert len(missions_response.json()) == 1

        mission_id = body["id"]
        detail_response = client.get(f"/atlas/missions/{mission_id}")
        assert detail_response.status_code == 200, detail_response.text
        assert detail_response.json()["title"] == "Growth campaign"

        patch_response = client.patch(
            f"/atlas/missions/{mission_id}",
            json={"status": "in_progress", "progress": 25, "result": {"note": "started"}},
        )
        assert patch_response.status_code == 200, patch_response.text
        patched = patch_response.json()
        assert patched["status"] == "in_progress"
        assert patched["progress"] == 25
        assert patched["result"] == {"note": "started"}
