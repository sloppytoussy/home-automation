from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dashboard import app as hub_app


def sample_config() -> dict:
    return {
        "services": [
            {"id": "dns_monitor", "name": "DNS monitor", "url": "http://dns:5000", "metrics_endpoint": "/api/summary", "port": 5000},
            {"id": "power_dashboard", "name": "Power dashboard", "url": "http://power:5001", "metrics_endpoint": "/api/summary", "port": 5001},
            {"id": "water_monitor", "name": "Water monitor", "url": "http://water:5002", "metrics_endpoint": "/api/tanks", "port": 5002},
            {"id": "solar_battery", "name": "Solar & battery", "url": "http://solar:5003", "metrics_endpoint": "/api/solar/summary", "port": 5003},
            {"id": "lighting_control", "name": "Lighting control", "url": "http://lighting:5005", "metrics_endpoint": "/api/lighting/overview", "port": 5005},
        ],
        "infrastructure": {
            "influxdb": {"url": "http://influxdb:8086", "health_path": "/health"},
            "grafana": {"url": "http://grafana:3000", "health_path": "/api/health"},
            "mqtt": {"host": "mosquitto", "port": 1883},
        },
        "hub": {"fetch_timeout_seconds": 2, "refresh_interval_seconds": 30},
    }


SERVICE_DATA = {
    "http://dns:5000/api/summary": {"dns_queries_today": 1200, "ads_percentage_today": 14.5},
    "http://power:5001/api/summary": {"remaining_kwh": 45.5, "days_left": 7, "consumption_rate_kwh_per_day": 6.4},
    "http://water:5002/api/tanks": [{"id": "main", "name": "Main", "level_pct": 72, "volume_liters": 7200}],
    "http://solar:5003/api/solar/summary": {"battery_soc_pct": 66, "pv_power_w": 820, "data_available": True},
    "http://lighting:5005/api/lighting/overview": {"devices_on": 4, "devices_total": 12, "total_power_w": 88.2},
}


class FakeResponse:
    def __init__(self, data=None, status_code=200, json_error=False):
        self.data = data
        self.status_code = status_code
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise ValueError("bad json")
        return self.data


class FakeSocket:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


@pytest.fixture
def client(monkeypatch):
    hub_app.app.config.update(TESTING=True)
    monkeypatch.setattr(hub_app, "load_config", sample_config)
    return hub_app.app.test_client()


@pytest.fixture
def admin_session(client):
    with client.session_transaction() as sess:
        sess["username"] = "owner"
        sess["role"] = "admin"
        sess["display_name"] = "Owner"
    return client


@pytest.fixture
def user_session(client):
    with client.session_transaction() as sess:
        sess["username"] = "viewer"
        sess["role"] = "user"
        sess["display_name"] = "Viewer"
    return client


def patch_requests(monkeypatch, overrides=None, failures=None):
    overrides = overrides or {}
    failures = failures or set()

    def fake_get(url, timeout):
        if url in failures:
            raise requests.exceptions.Timeout("timeout")
        if url in overrides:
            value = overrides[url]
            if isinstance(value, Exception):
                raise value
            return value
        if url in SERVICE_DATA:
            return FakeResponse(SERVICE_DATA[url])
        if url in ("http://influxdb:8086/health", "http://grafana:3000/api/health"):
            return FakeResponse({"ok": True}, status_code=200)
        raise requests.exceptions.ConnectionError("unexpected url")

    monkeypatch.setattr(hub_app.requests, "get", fake_get)


def patch_socket(monkeypatch, online=True):
    if online:
        monkeypatch.setattr(hub_app.socket, "create_connection", lambda address, timeout: FakeSocket())
    else:
        def fail(address, timeout):
            raise OSError("down")
        monkeypatch.setattr(hub_app.socket, "create_connection", fail)


def patch_all_online(monkeypatch):
    patch_requests(monkeypatch)
    patch_socket(monkeypatch, True)


def test_overview_all_services_online(client, monkeypatch):
    patch_all_online(monkeypatch)
    response = client.get("/api/hub/overview")
    data = response.get_json()
    assert response.status_code == 200
    assert data["services_online"] == 5
    assert data["services_total"] == 5
    assert data["data_available"] is True
    assert len(data["services"]) == 5


def test_overview_shape_includes_infrastructure(client, monkeypatch):
    patch_all_online(monkeypatch)
    data = client.get("/api/hub/overview").get_json()
    assert set(data["infrastructure"]) == {"influxdb", "grafana", "mqtt"}


def test_overview_service_shape(client, monkeypatch):
    patch_all_online(monkeypatch)
    service = client.get("/api/hub/overview").get_json()["services"][0]
    assert set(service) == {"id", "name", "port", "url", "online", "data_available", "key_metrics", "last_updated"}


def test_overview_one_service_times_out(client, monkeypatch):
    patch_requests(monkeypatch, failures={"http://solar:5003/api/solar/summary"})
    patch_socket(monkeypatch, True)
    data = client.get("/api/hub/overview").get_json()
    solar = next(service for service in data["services"] if service["id"] == "solar_battery")
    assert data["services_online"] == 4
    assert solar["online"] is False


def test_overview_timeout_does_not_affect_others(client, monkeypatch):
    patch_requests(monkeypatch, failures={"http://solar:5003/api/solar/summary"})
    patch_socket(monkeypatch, True)
    data = client.get("/api/hub/overview").get_json()
    lighting = next(service for service in data["services"] if service["id"] == "lighting_control")
    assert lighting["online"] is True


def test_overview_all_services_offline(client, monkeypatch):
    patch_requests(monkeypatch, failures=set(SERVICE_DATA))
    patch_socket(monkeypatch, False)
    response = client.get("/api/hub/overview")
    data = response.get_json()
    assert response.status_code == 200
    assert data["services_online"] == 0


def test_overview_all_services_offline_keeps_shape(client, monkeypatch):
    patch_requests(monkeypatch, failures=set(SERVICE_DATA))
    patch_socket(monkeypatch, False)
    data = client.get("/api/hub/overview").get_json()
    assert len(data["services"]) == 5
    assert all(service["key_metrics"] == {} for service in data["services"])


def test_overview_service_returns_500_offline(client, monkeypatch):
    patch_requests(monkeypatch, overrides={"http://power:5001/api/summary": FakeResponse({"error": "down"}, 500)})
    patch_socket(monkeypatch, True)
    data = client.get("/api/hub/overview").get_json()
    power = next(service for service in data["services"] if service["id"] == "power_dashboard")
    assert power["online"] is False


def test_overview_service_returns_404_online(client, monkeypatch):
    patch_requests(monkeypatch, overrides={"http://power:5001/api/summary": FakeResponse({"error": "missing"}, 404)})
    patch_socket(monkeypatch, True)
    data = client.get("/api/hub/overview").get_json()
    power = next(service for service in data["services"] if service["id"] == "power_dashboard")
    assert power["online"] is True


def test_overview_invalid_json_online_no_data(client, monkeypatch):
    patch_requests(monkeypatch, overrides={"http://dns:5000/api/summary": FakeResponse(status_code=200, json_error=True)})
    patch_socket(monkeypatch, True)
    data = client.get("/api/hub/overview").get_json()
    dns = next(service for service in data["services"] if service["id"] == "dns_monitor")
    assert dns["online"] is True
    assert dns["data_available"] is False


def test_overview_empty_json_waiting(client, monkeypatch):
    patch_requests(monkeypatch, overrides={"http://dns:5000/api/summary": FakeResponse({})})
    patch_socket(monkeypatch, True)
    data = client.get("/api/hub/overview").get_json()
    dns = next(service for service in data["services"] if service["id"] == "dns_monitor")
    assert dns["online"] is True
    assert dns["data_available"] is False


def test_overview_has_last_updated(client, monkeypatch):
    patch_all_online(monkeypatch)
    assert client.get("/api/hub/overview").get_json()["last_updated"]


def test_service_last_updated_when_data_available(client, monkeypatch):
    patch_all_online(monkeypatch)
    service = client.get("/api/hub/overview").get_json()["services"][0]
    assert service["last_updated"]


def test_service_last_updated_null_without_data(client, monkeypatch):
    patch_requests(monkeypatch, overrides={"http://dns:5000/api/summary": FakeResponse({})})
    patch_socket(monkeypatch, True)
    service = client.get("/api/hub/overview").get_json()["services"][0]
    assert service["last_updated"] is None


def test_influxdb_health_check_online(monkeypatch):
    patch_requests(monkeypatch)
    assert hub_app.check_infrastructure(sample_config())["influxdb"]["online"] is True


def test_influxdb_health_check_offline(monkeypatch):
    patch_requests(monkeypatch, overrides={"http://influxdb:8086/health": FakeResponse({}, 503)})
    assert hub_app.check_infrastructure(sample_config())["influxdb"]["online"] is False


def test_influxdb_health_check_exception_offline(monkeypatch):
    patch_requests(monkeypatch, overrides={"http://influxdb:8086/health": requests.exceptions.ConnectionError("down")})
    assert hub_app.check_infrastructure(sample_config())["influxdb"]["online"] is False


def test_grafana_health_check_online(monkeypatch):
    patch_requests(monkeypatch)
    assert hub_app.check_infrastructure(sample_config())["grafana"]["online"] is True


def test_grafana_health_check_offline(monkeypatch):
    patch_requests(monkeypatch, overrides={"http://grafana:3000/api/health": FakeResponse({}, 500)})
    assert hub_app.check_infrastructure(sample_config())["grafana"]["online"] is False


def test_grafana_health_check_exception_offline(monkeypatch):
    patch_requests(monkeypatch, overrides={"http://grafana:3000/api/health": requests.exceptions.ConnectionError("down")})
    assert hub_app.check_infrastructure(sample_config())["grafana"]["online"] is False


def test_mqtt_check_online(monkeypatch):
    patch_requests(monkeypatch)
    patch_socket(monkeypatch, True)
    assert hub_app.check_infrastructure(sample_config())["mqtt"]["online"] is True


def test_mqtt_check_offline(monkeypatch):
    patch_requests(monkeypatch)
    patch_socket(monkeypatch, False)
    assert hub_app.check_infrastructure(sample_config())["mqtt"]["online"] is False


def test_mqtt_check_includes_host_port(monkeypatch):
    patch_requests(monkeypatch)
    patch_socket(monkeypatch, True)
    mqtt = hub_app.check_infrastructure(sample_config())["mqtt"]
    assert mqtt["host"] == "mosquitto"
    assert mqtt["port"] == 1883


def test_extract_lighting_metrics():
    assert hub_app.extract_metrics("lighting_control", {"devices_on": 3, "devices_total": 8, "total_power_w": 42.0}) == {
        "devices_on": 3,
        "devices_total": 8,
        "total_power_w": 42.0,
    }


def test_extract_water_metrics():
    result = hub_app.extract_metrics("water_monitor", [{"id": "tank_1", "name": "Tank 1", "level_pct": 80, "volume_liters": 8000}])
    assert result["tanks"][0]["level_pct"] == 80


def test_extract_solar_metrics():
    result = hub_app.extract_metrics("solar_battery", {"battery_soc_pct": 77, "pv_power_w": 900, "data_available": True})
    assert result == {"battery_soc_pct": 77, "pv_power_w": 900, "data_available": True}


def test_extract_dns_metrics():
    result = hub_app.extract_metrics("dns_monitor", {"dns_queries_today": 99, "ads_percentage_today": 21.2})
    assert result == {"queries_today": 99, "blocked_pct": 21.2}


def test_extract_power_metrics():
    result = hub_app.extract_metrics("power_dashboard", {"remaining_kwh": 20, "days_left": 3, "consumption_rate_kwh_per_day": 6})
    assert result == {"remaining_kwh": 20, "days_left": 3, "consumption_rate_kwh_per_day": 6}


def test_extract_unknown_service():
    assert hub_app.extract_metrics("unknown_service", {}) == {}


def test_extract_missing_metric_key_none():
    result = hub_app.extract_metrics("lighting_control", {"devices_on": 2})
    assert result["devices_total"] is None


def test_extract_water_non_list_no_raise():
    assert hub_app.extract_metrics("water_monitor", {}) == {"tanks": []}


def test_extract_water_skips_non_dict():
    assert hub_app.extract_metrics("water_monitor", ["bad", {"id": "tank"}]) == {
        "tanks": [{"id": "tank", "name": None, "level_pct": None, "volume_liters": None}]
    }


def test_extract_non_dict_for_dns_no_raise():
    assert hub_app.extract_metrics("dns_monitor", []) == {"queries_today": None, "blocked_pct": None}


def test_status_route_returns_online(client, monkeypatch):
    patch_all_online(monkeypatch)
    data = client.get("/api/hub/status").get_json()
    assert data["online"] is True


def test_status_route_service_counts(client, monkeypatch):
    patch_requests(monkeypatch, failures={"http://dns:5000/api/summary"})
    patch_socket(monkeypatch, True)
    data = client.get("/api/hub/status").get_json()
    assert data["services_total"] == 5
    assert data["services_online"] == 4


def test_status_route_has_last_updated(client, monkeypatch):
    patch_all_online(monkeypatch)
    assert client.get("/api/hub/status").get_json()["last_updated"]


def test_index_unauthenticated_redirects(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_index_authenticated_returns_200(client):
    with client.session_transaction() as sess:
        sess["username"] = "owner"
        sess["role"] = "admin"
    response = client.get("/")
    assert response.status_code == 200
    assert b"Home Automation" in response.data


def test_auth_me_admin_returns_admin_role(client, admin_session):
    response = client.get("/auth/me")
    assert response.status_code == 200
    data = response.get_json()
    assert data["role"] == "admin"
    assert data["logged_in"] is True


def test_auth_me_user_returns_user_role(client, user_session):
    response = client.get("/auth/me")
    assert response.status_code == 200
    assert response.get_json()["role"] == "user"


def test_config_url_override(monkeypatch, tmp_path):
    config_file = tmp_path / "hub.yaml"
    config_file.write_text("services:\n  - id: dns_monitor\n    url: http://old:5000\n", encoding="utf-8")
    monkeypatch.setattr(hub_app, "CONFIG_PATH", config_file)
    monkeypatch.setenv("HUB_SERVICE_DNS_MONITOR_URL", "http://new:5000")
    assert hub_app.load_config()["services"][0]["url"] == "http://new:5000"


def test_load_config_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(hub_app, "CONFIG_PATH", tmp_path / "missing.yaml")
    assert hub_app.load_config() == {}


def test_hub_timeout_from_config():
    assert hub_app.hub_timeout(sample_config()) == 2


def test_hub_timeout_default():
    assert hub_app.hub_timeout({}) == 2


def test_service_result_success(monkeypatch):
    patch_requests(monkeypatch)
    result = hub_app.service_result(sample_config()["services"][0], 2)
    assert result["online"] is True
    assert result["key_metrics"]["queries_today"] == 1200


def test_service_result_timeout(monkeypatch):
    patch_requests(monkeypatch, failures={"http://dns:5000/api/summary"})
    result = hub_app.service_result(sample_config()["services"][0], 2)
    assert result["online"] is False


def test_check_http_health_uses_status_200(monkeypatch):
    get = MagicMock(return_value=FakeResponse({}, 200))
    monkeypatch.setattr(hub_app.requests, "get", get)
    assert hub_app.check_http_health("http://service", "/health", 2) is True
    get.assert_called_once_with("http://service/health", timeout=2)


def test_check_mqtt_health_uses_timeout(monkeypatch):
    create_connection = MagicMock(return_value=FakeSocket())
    monkeypatch.setattr(hub_app.socket, "create_connection", create_connection)
    assert hub_app.check_mqtt_health("host", 1883, 2) is True
    create_connection.assert_called_once_with(("host", 1883), timeout=2)


def test_api_hub_overview_value_error_returns_400(client, monkeypatch):
    def fail():
        raise ValueError("bad")
    monkeypatch.setattr(hub_app, "overview_payload", fail)
    response = client.get("/api/hub/overview")
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid input"}


def test_api_hub_overview_unexpected_error_returns_503(client, monkeypatch):
    def fail():
        raise RuntimeError("bad")
    monkeypatch.setattr(hub_app, "overview_payload", fail)
    response = client.get("/api/hub/overview")
    assert response.status_code == 503
    assert response.get_json() == {"error": "service unavailable"}
