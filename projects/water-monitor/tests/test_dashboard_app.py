from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dashboard import app as water_app


@pytest.fixture
def client():
    water_app.app.config.update(TESTING=True)
    return water_app.app.test_client()


def authenticate(client, role: str = "admin"):
    with client.session_transaction() as saved_session:
        saved_session["username"] = "owner" if role == "admin" else "viewer"
        saved_session["role"] = role


def test_index_route_requires_auth(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_index_route_authenticated_returns_dashboard(client):
    authenticate(client)
    response = client.get("/")
    assert response.status_code == 200
    assert b"Water Monitor" in response.data


def test_api_route_requires_auth_json(client):
    response = client.get("/api/tanks", headers={"Accept": "application/json"})
    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication required"}


def test_api_route_authenticated_returns_data(client, monkeypatch):
    authenticate(client)
    monkeypatch.setattr(
        water_app,
        "load_tanks",
        lambda: [{
            "id": "tank1",
            "name": "Main",
            "capacity_liters": 1000,
            "sources": ["mains"],
        }],
    )
    monkeypatch.setattr(water_app, "latest_reading", lambda tank_id: {"volume_liters": 500})
    monkeypatch.setattr(water_app, "rolling_rate_lph", lambda tank_id: 10)
    monkeypatch.setattr(water_app, "today_consumption_l", lambda tank_id: 12)
    monkeypatch.setattr(water_app, "avg_daily_consumption_l", lambda tank_id: 15)
    monkeypatch.setattr(water_app, "pump_status", lambda tank: {"running": False})
    monkeypatch.setattr(water_app, "sensor_status", lambda tank_id: {"battery_pct": None})

    response = client.get("/api/tanks")

    assert response.status_code == 200
    assert response.get_json()[0]["id"] == "tank1"


def test_source_update_rejects_non_admin(client):
    authenticate(client, role="user")
    response = client.post("/api/source/tank2", json={"source": "mains"})
    assert response.status_code == 403
    assert response.get_json() == {"error": "admin access required"}


def test_source_update_allows_admin(client, monkeypatch, tmp_path):
    authenticate(client)
    config_path = tmp_path / "tanks.yaml"
    config_path.write_text(
        "tanks:\n"
        "  - id: tank2\n"
        "    name: Secondary\n"
        "    sources: [rain, mains]\n"
        "    active_source: rain\n"
    )
    monkeypatch.setattr(water_app, "CONFIG_PATH", config_path)
    monkeypatch.setattr(
        water_app,
        "load_tanks",
        lambda: [{
            "id": "tank2",
            "name": "Secondary",
            "sources": ["rain", "mains"],
            "active_source": "rain",
        }],
    )

    response = client.post("/api/source/tank2", json={"source": "mains"})

    assert response.status_code == 200
    assert response.get_json() == {"tank_id": "tank2", "active_source": "mains"}
    assert "active_source: mains" in config_path.read_text()
