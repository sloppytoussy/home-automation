from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dashboard import app as lighting_app


@pytest.fixture
def client():
    lighting_app.app.config.update(TESTING=True)
    test_client = lighting_app.app.test_client()
    authenticate(test_client)
    return test_client


@pytest.fixture
def anonymous_client():
    lighting_app.app.config.update(TESTING=True)
    return lighting_app.app.test_client()


@pytest.fixture
def auth_session(client):
    authenticate(client, role="admin")
    return client


@pytest.fixture
def user_auth_session(client):
    authenticate(client, role="user")
    return client


def authenticate(client, role: str = "admin"):
    with client.session_transaction() as saved_session:
        saved_session["username"] = "admin" if role == "admin" else "viewer"
        saved_session["role"] = role
        saved_session["display_name"] = "Admin" if role == "admin" else "Viewer"


def row(device_id="living_room_main", minutes=1, **overrides):
    data = {
        "time": datetime.now(timezone.utc) - timedelta(minutes=minutes),
        "device_id": device_id,
        "room": "living_room" if device_id == "living_room_main" else "bedroom",
        "device_type": "shellyplus1pm",
        "generation": "gen2",
        "is_on": True,
        "brightness_pct": None,
        "power_w": 42.5,
    }
    data.update(overrides)
    return data


def rows():
    return [
        row("living_room_main", 1, is_on=True, power_w=42.5),
        row("bedroom_lamp", 10, room="bedroom", device_type="shelly1", generation="gen1", is_on=False, power_w=None),
    ]


def patch_rows(monkeypatch, data):
    monkeypatch.setattr(lighting_app, "latest_device_rows", lambda: data)


def patch_error(monkeypatch):
    def raise_error():
        raise RuntimeError("boom")
    monkeypatch.setattr(lighting_app, "latest_device_rows", raise_error)


def test_index_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Lighting Control" in response.data


def test_index_unauthenticated_redirects(anonymous_client):
    response = anonymous_client.get("/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_auth_me_logged_in_returns_user(client, auth_session):
    response = client.get("/auth/me")
    assert response.status_code == 200
    data = response.get_json()
    assert data["logged_in"] is True
    assert "username" in data
    assert "role" in data


def test_auth_me_not_logged_in_returns_logged_out(anonymous_client):
    response = anonymous_client.get("/auth/me")
    assert response.status_code == 200
    assert response.get_json()["logged_in"] is False


def test_api_route_requires_auth_json(anonymous_client):
    response = anonymous_client.get(
        "/api/lighting/overview",
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication required"}


def test_overview_happy_path(client, monkeypatch):
    patch_rows(monkeypatch, rows())
    response = client.get("/api/lighting/overview")
    data = response.get_json()
    assert response.status_code == 200
    assert data["data_available"] is True
    assert data["devices_total"] == 2
    assert data["devices_on"] == 1
    assert data["rooms_total"] == 2
    assert data["rooms_with_lights_on"] == 1
    assert data["total_power_w"] == 42.5


def test_overview_no_data(client, monkeypatch):
    patch_rows(monkeypatch, [])
    response = client.get("/api/lighting/overview")
    data = response.get_json()
    assert response.status_code == 200
    assert data["data_available"] is False
    assert data["devices_total"] is None
    assert data["total_power_w"] is None


def test_overview_influxdb_unavailable(client, monkeypatch):
    patch_error(monkeypatch)
    response = client.get("/api/lighting/overview")
    assert response.status_code == 503
    assert response.get_json() == {"error": "service unavailable"}


def test_devices_list_shape(client, monkeypatch):
    patch_rows(monkeypatch, rows())
    response = client.get("/api/lighting/devices")
    data = response.get_json()
    assert response.status_code == 200
    assert data[0]["device_id"] == "living_room_main"
    assert data[0]["name"] == "Living Room Main"
    assert data[0]["online"] is True


def test_devices_online_flag_stale_false(client, monkeypatch):
    patch_rows(monkeypatch, [row(minutes=6)])
    response = client.get("/api/lighting/devices")
    assert response.get_json()[0]["online"] is False


def test_devices_empty(client, monkeypatch):
    patch_rows(monkeypatch, [])
    response = client.get("/api/lighting/devices")
    assert response.status_code == 200
    assert response.get_json() == []


def test_devices_influxdb_unavailable(client, monkeypatch):
    patch_error(monkeypatch)
    response = client.get("/api/lighting/devices")
    assert response.status_code == 503


def test_single_device_happy_path(client, monkeypatch):
    patch_rows(monkeypatch, rows())
    response = client.get("/api/lighting/devices/living_room_main")
    assert response.status_code == 200
    assert response.get_json()["device_id"] == "living_room_main"


def test_single_device_unknown(client, monkeypatch):
    patch_rows(monkeypatch, rows())
    response = client.get("/api/lighting/devices/missing")
    assert response.status_code == 404
    assert response.get_json() == {"error": "device not found"}


def test_single_device_no_data_for_known_returns_404(client, monkeypatch):
    patch_rows(monkeypatch, [])
    response = client.get("/api/lighting/devices/living_room_main")
    assert response.status_code == 404


@pytest.mark.parametrize("body,event_type", [({"on": True}, "on"), ({"on": False}, "off"), ({"brightness": 55}, "dim")])
def test_set_device_valid_commands(client, monkeypatch, body, event_type):
    published = []
    monkeypatch.setattr(lighting_app, "publish_command", lambda device, payload: published.append((device, payload)))
    write_event = MagicMock()
    monkeypatch.setattr(lighting_app.writer, "write_event", write_event)
    response = client.post("/api/lighting/devices/living_room_main/set", json=body)
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    assert published
    assert write_event.call_args.args[3] == event_type


@pytest.mark.parametrize("body", [{"brightness": 101}, {"brightness": -1}, {}, {"on": "yes"}, None])
def test_set_device_invalid_body(client, body):
    response = client.post("/api/lighting/devices/living_room_main/set", json=body)
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid input"}


def test_set_unknown_device(client):
    response = client.post("/api/lighting/devices/missing/set", json={"on": True})
    assert response.status_code == 404


def test_set_mqtt_unavailable(client, monkeypatch):
    def fail(device, payload):
        raise OSError("down")
    monkeypatch.setattr(lighting_app, "publish_command", fail)
    response = client.post("/api/lighting/devices/living_room_main/set", json={"on": True})
    assert response.status_code == 503


def test_device_toggle_requires_auth(anonymous_client):
    response = anonymous_client.post(
        "/api/lighting/devices/living_room_main/set",
        json={"on": True},
    )
    assert response.status_code in (302, 401)


@pytest.mark.xfail(
    reason="Toggle route uses @require_admin until Phase 5 changes it to @require_auth",
    strict=True,
)
def test_device_toggle_allowed_for_user_role(client, user_auth_session):
    response = client.post(
        "/api/lighting/devices/living_room_main/set",
        json={"on": True},
    )
    assert response.status_code in (200, 404, 503)


def test_set_device_rejects_non_admin(client):
    authenticate(client, role="user")
    response = client.post("/api/lighting/devices/living_room_main/set", json={"on": True})
    assert response.status_code == 403
    assert response.get_json() == {"error": "admin access required"}


def test_rooms_list_shape(client, monkeypatch):
    patch_rows(monkeypatch, rows())
    response = client.get("/api/lighting/rooms")
    data = response.get_json()
    assert response.status_code == 200
    assert data[0]["room_id"] == "bedroom"
    assert data[1]["room_id"] == "living_room"


def test_rooms_empty(client, monkeypatch):
    patch_rows(monkeypatch, [])
    response = client.get("/api/lighting/rooms")
    assert response.status_code == 200
    assert response.get_json() == []


def test_rooms_influxdb_unavailable(client, monkeypatch):
    patch_error(monkeypatch)
    response = client.get("/api/lighting/rooms")
    assert response.status_code == 503


def history_data():
    return [{"time": datetime.now(timezone.utc), "is_on": True, "power_w": 20.0, "brightness_pct": 80.0}]


def test_history_default_24h(client, monkeypatch):
    seen = {}
    def fake_history(device_id, hours):
        seen["args"] = (device_id, hours)
        return history_data()
    monkeypatch.setattr(lighting_app, "history_rows", fake_history)
    response = client.get("/api/lighting/history?device_id=living_room_main")
    assert response.status_code == 200
    assert seen["args"] == ("living_room_main", 24)


def test_history_custom_48h(client, monkeypatch):
    seen = {}
    def fake_history(device_id, hours):
        seen["hours"] = hours
        return []
    monkeypatch.setattr(lighting_app, "history_rows", fake_history)
    response = client.get("/api/lighting/history?device_id=living_room_main&hours=48")
    assert response.status_code == 200
    assert seen["hours"] == 48


@pytest.mark.parametrize("hours", ["0", "169", "abc", "-1"])
def test_history_invalid_hours(client, hours):
    response = client.get(f"/api/lighting/history?device_id=living_room_main&hours={hours}")
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid input"}


def test_history_unknown_device(client):
    response = client.get("/api/lighting/history?device_id=missing")
    assert response.status_code == 404


def test_history_missing_device_id(client):
    response = client.get("/api/lighting/history")
    assert response.status_code == 404


def test_history_influxdb_unavailable(client, monkeypatch):
    def fail(device_id, hours):
        raise RuntimeError("boom")
    monkeypatch.setattr(lighting_app, "history_rows", fail)
    response = client.get("/api/lighting/history?device_id=living_room_main")
    assert response.status_code == 503


def test_status_with_data(client, monkeypatch):
    patch_rows(monkeypatch, rows())
    response = client.get("/api/lighting/status")
    data = response.get_json()
    assert response.status_code == 200
    assert data["data_available"] is True
    assert data["device_count"] == 2
    assert data["mqtt_connected"] is True


def test_status_no_influxdb_data(client, monkeypatch):
    patch_rows(monkeypatch, [])
    response = client.get("/api/lighting/status")
    data = response.get_json()
    assert response.status_code == 200
    assert data["data_available"] is False
    assert data["last_event_minutes_ago"] is None


def test_status_influxdb_unavailable(client, monkeypatch):
    patch_error(monkeypatch)
    response = client.get("/api/lighting/status")
    assert response.status_code == 503


@pytest.mark.parametrize("value,expected", [(None, None), ("bad", None), (datetime.now(timezone.utc), True)])
def test_iso_time(value, expected):
    result = lighting_app.iso_time(value)
    assert (result is not None) is bool(expected)


@pytest.mark.parametrize(
    ("device", "body", "expected_topic"),
    [
        ({"generation": "gen1", "shelly_id": "abc", "dimmable": False}, {"on": True}, "shellies/abc/relay/0/command"),
        ({"generation": "gen2", "shelly_id": "abc", "dimmable": False}, {"on": True}, "abc/rpc"),
        ({"generation": "gen2", "shelly_id": "abc", "dimmable": True}, {"brightness": 50}, "abc/rpc"),
    ],
)
def test_publish_command_topics(monkeypatch, device, body, expected_topic):
    client = MagicMock()
    monkeypatch.setattr(lighting_app, "mqtt_client", lambda: client)
    lighting_app.publish_command(device, body)
    assert client.publish.call_args.args[0] == expected_topic
    client.disconnect.assert_called_once()


def test_overview_from_devices_empty():
    assert lighting_app.overview_from_devices([])["data_available"] is False


def test_normalize_device_uses_config_name():
    data = lighting_app.normalize_device(row("living_room_main"))
    assert data["name"] == "Living Room Main"


def test_rooms_from_devices_power_sum():
    data = lighting_app.rooms_from_devices([lighting_app.normalize_device(item) for item in rows()])
    living = [item for item in data if item["room_id"] == "living_room"][0]
    assert living["total_power_w"] == 42.5


def test_bad_request_shape(client):
    with lighting_app.app.app_context():
        response, status = lighting_app.bad_request(ValueError("bad"))
    assert status == 400
    assert response.get_json() == {"error": "invalid input"}


def test_service_error_shape(client):
    with lighting_app.app.app_context():
        response, status = lighting_app.service_error(RuntimeError("bad"))
    assert status == 503
    assert response.get_json() == {"error": "service unavailable"}
