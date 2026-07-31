import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import app.main as main_module

from app.main import app


client = TestClient(app)


def test_root_endpoint() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "AEA Core API is running"}


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "aea-core-backend"
    assert "supabase_configured" in payload
    assert "supabase_connected" in payload


def test_workers_endpoint_returns_mock_data_when_supabase_is_unavailable() -> None:
    response = client.get("/workers")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload[0]["name"] == "Atlas"


def test_create_worker_reports_supabase_errors(monkeypatch) -> None:
    class FailingTable:
        def insert(self, payload):
            raise RuntimeError("new row violates row-level security policy")

    class FailingClient:
        def table(self, _name):
            return FailingTable()

    monkeypatch.setattr(main_module, "supabase_client", FailingClient())

    response = client.post(
        "/workers",
        json={"name": "Test Bot", "role": "affiliate", "status": "active"},
    )

    assert response.status_code == 500
    assert "row-level security policy" in response.json()["detail"]
