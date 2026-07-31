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

    def select(self, *_args, **_kwargs):
        self._method = "select"
        return self

    def insert(self, payload: dict):
        self._method = "insert"
        self._payload = payload
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
                "goal": "Launch an affiliate campaign for Pinterest traffic",
                "target_products": 3,
                "target_pins": 12,
                "campaign_name": "summer-promo",
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["mission_id"] is not None
        assert body["steps"][0]["step_name"] == "Research Worker"
        assert body["first_command"]["command_type"] == "START_RESEARCH"

        missions_response = client.get("/atlas/missions")
        assert missions_response.status_code == 200, missions_response.text
        assert len(missions_response.json()) == 1
