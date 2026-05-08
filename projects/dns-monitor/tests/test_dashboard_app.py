from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dashboard import app as dns_app


@pytest.fixture
def client():
    dns_app.app.config.update(TESTING=True)
    return dns_app.app.test_client()


def authenticate(client, role: str = "admin"):
    with client.session_transaction() as saved_session:
        saved_session["username"] = "owner" if role == "admin" else "viewer"
        saved_session["role"] = role


class FakePiHole:
    def summary(self):
        return {"dns_queries_today": 100, "ads_percentage_today": 12.5}


def test_index_route_requires_auth(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_index_route_authenticated_returns_dashboard(client):
    authenticate(client)
    response = client.get("/")
    assert response.status_code == 200
    assert b"DNS Monitor" in response.data


def test_api_route_requires_auth_json(client):
    response = client.get("/api/summary", headers={"Accept": "application/json"})
    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication required"}


def test_api_route_authenticated_returns_data(client, monkeypatch):
    authenticate(client)
    monkeypatch.setattr(dns_app, "get_pihole", lambda: FakePiHole())
    response = client.get("/api/summary")
    assert response.status_code == 200
    assert response.get_json()["dns_queries_today"] == 100
