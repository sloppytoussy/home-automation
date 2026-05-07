from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

DEV_SERVER_PATH = Path(__file__).resolve().parent / "dev_server.py"

spec = importlib.util.spec_from_file_location("water_monitor_dev_server", DEV_SERVER_PATH)
dev_server = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(dev_server)

REQUIRED_TANK_FIELDS = {
    "id",
    "name",
    "capacity_liters",
    "sources",
    "active_source",
    "level_pct",
    "volume_liters",
    "depth_cm",
    "water_depth_cm",
    "drain_rate_lph",
    "days_remaining",
    "todays_use_liters",
    "status",
    "last_updated",
    "pump",
    "sensor",
}

SCENARIO_NAMES = sorted(dev_server.SCENARIOS)


@pytest.fixture
def client():
    dev_server.current_tanks = dev_server.build_scenario("normal")
    dev_server.app.config.update(TESTING=True)
    with dev_server.app.test_client() as test_client:
        yield test_client


def tank_by_id(tanks: list[dict], tank_id: str) -> dict:
    return next(tank for tank in tanks if tank["id"] == tank_id)


@pytest.mark.parametrize("scenario", SCENARIO_NAMES)
def test_all_scenarios_return_two_tanks(client, scenario):
    response = client.get(f"/api/water/scenario?name={scenario}")

    assert response.status_code == 200
    assert len(response.get_json()) == 2


@pytest.mark.parametrize("scenario", SCENARIO_NAMES)
def test_scenario_response_has_required_tank_fields(client, scenario):
    response = client.get(f"/api/water/scenario?name={scenario}")
    tanks = response.get_json()

    for tank in tanks:
        assert REQUIRED_TANK_FIELDS.issubset(tank)


@pytest.mark.parametrize("scenario", SCENARIO_NAMES)
def test_scenario_response_has_dashboard_compatibility_fields(client, scenario):
    response = client.get(f"/api/water/scenario?name={scenario}")
    tanks = response.get_json()

    for tank in tanks:
        assert "reading" in tank
        assert "rate_lph" in tank
        assert "days_left" in tank
        assert "today_consumption_l" in tank
        assert "avg_consumption_l" in tank


def test_unknown_scenario_returns_available_names(client):
    response = client.get("/api/water/scenario?name=unknown")

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "unknown scenario"
    assert body["available"] == SCENARIO_NAMES


def test_api_tanks_returns_both_tanks(client):
    response = client.get("/api/tanks")

    assert response.status_code == 200
    assert {tank["id"] for tank in response.get_json()} == {"tank1", "tank2"}


def test_api_tanks_required_fields_present(client):
    response = client.get("/api/tanks")

    for tank in response.get_json():
        assert REQUIRED_TANK_FIELDS.issubset(tank)
        assert {"name", "state", "runtime_today_min", "last_seen_min"}.issubset(tank["pump"])
        assert {"battery_pct", "last_seen_min"}.issubset(tank["sensor"])


def test_history_tank1_returns_non_empty_list(client):
    response = client.get("/api/history/tank1")

    assert response.status_code == 200
    assert len(response.get_json()) > 0


def test_history_tank2_returns_non_empty_list(client):
    response = client.get("/api/history/tank2")

    assert response.status_code == 200
    assert len(response.get_json()) > 0


def test_history_unknown_tank_returns_404(client):
    response = client.get("/api/history/tank3")

    assert response.status_code == 404


@pytest.mark.parametrize("tank_id", ["tank1", "tank2"])
def test_history_rows_have_time_and_value(client, tank_id):
    response = client.get(f"/api/history/{tank_id}")
    first = response.get_json()[0]

    assert set(first) == {"time", "value"}


def test_consumption_returns_about_90_entries(client):
    response = client.get("/api/consumption?days=90")

    assert response.status_code == 200
    assert 85 <= len(response.get_json()) <= 95


def test_consumption_rows_match_production_shape(client):
    response = client.get("/api/consumption?days=90")
    first = response.get_json()[0]

    assert set(first) == {"date", "liters"}
    assert first == {"date": "2026-02-06", "liters": 144}
    assert isinstance(first["liters"], int)


def test_consumption_respects_days_query(client):
    response = client.get("/api/consumption?days=7")

    assert response.status_code == 200
    assert len(response.get_json()) == 7


def test_consumption_rejects_non_integer_days(client):
    response = client.get("/api/consumption?days=soon")

    assert response.status_code == 400


def test_consumption_rejects_zero_days(client):
    response = client.get("/api/consumption?days=0")

    assert response.status_code == 400


def test_post_source_tank2_updates_to_mains(client):
    response = client.post("/api/source/tank2", json={"source": "mains"})

    assert response.status_code == 200
    assert response.get_json() == {"tank_id": "tank2", "active_source": "mains"}
    tanks_response = client.get("/api/tanks")
    assert tank_by_id(tanks_response.get_json(), "tank2")["active_source"] == "mains"


def test_post_source_tank2_invalid_source_returns_400(client):
    response = client.post("/api/source/tank2", json={"source": "invalid"})

    assert response.status_code == 400


def test_post_source_tank1_rain_returns_400(client):
    response = client.post("/api/source/tank1", json={"source": "rain"})

    assert response.status_code == 400


def test_post_source_unknown_tank_returns_404(client):
    response = client.post("/api/source/tank3", json={"source": "mains"})

    assert response.status_code == 404


def test_post_source_missing_json_returns_400(client):
    response = client.post("/api/source/tank2")

    assert response.status_code == 400


def test_low_tank1_scenario_sets_tank1_below_20_percent(client):
    response = client.get("/api/water/scenario?name=low_tank1")
    tank1 = tank_by_id(response.get_json(), "tank1")

    assert tank1["level_pct"] < 20


def test_low_both_scenario_sets_both_tanks_below_15_percent(client):
    response = client.get("/api/water/scenario?name=low_both")

    assert all(tank["level_pct"] < 15 for tank in response.get_json())


def test_full_scenario_sets_both_tanks_at_or_above_95_percent(client):
    response = client.get("/api/water/scenario?name=full")

    assert all(tank["level_pct"] >= 95 for tank in response.get_json())


def test_filling_scenario_sets_negative_tank1_drain_rate(client):
    response = client.get("/api/water/scenario?name=filling")
    tank1 = tank_by_id(response.get_json(), "tank1")

    assert tank1["drain_rate_lph"] < 0


def test_filling_scenario_sets_tank1_pump_running(client):
    response = client.get("/api/water/scenario?name=filling")
    tank1 = tank_by_id(response.get_json(), "tank1")

    assert tank1["pump"]["state"] == "running"


def test_sensor_offline_scenario_sets_both_sensors_stale(client):
    response = client.get("/api/water/scenario?name=sensor_offline")

    assert all(tank["sensor"]["last_seen_min"] > 60 for tank in response.get_json())


def test_sensor_offline_scenario_sets_status_stale(client):
    response = client.get("/api/water/scenario?name=sensor_offline")

    assert all(tank["status"] == "stale" for tank in response.get_json())


def test_normal_scenario_sets_both_tanks_above_50_percent(client):
    response = client.get("/api/water/scenario?name=normal")

    assert all(tank["level_pct"] > 50 for tank in response.get_json())


def test_scenario_updates_api_tanks_current_state(client):
    client.get("/api/water/scenario?name=low_tank1")
    response = client.get("/api/tanks")
    tank1 = tank_by_id(response.get_json(), "tank1")

    assert tank1["level_pct"] < 20


def test_dashboard_html_loads(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"Water Monitor" in response.data
