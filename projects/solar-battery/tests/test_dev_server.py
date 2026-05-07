from __future__ import annotations

from pathlib import Path
import sys

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tests import dev_server


@pytest.fixture
def client():
    dev_server.app.config.update(TESTING=True)
    return dev_server.app.test_client()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("low_battery", {"battery_soc_pct": 12.5, "mppt_state_label": "Off", "pv_power_w": 0.0}),
        ("charging", {"battery_soc_pct": 67.0, "mppt_state_label": "Bulk", "pv_power_w": 1050.0}),
        ("cloudy", {"battery_soc_pct": 45.0, "mppt_state_label": "Bulk", "pv_power_w": 180.0}),
        ("night", {"battery_soc_pct": 55.0, "mppt_state_label": "Off", "pv_power_w": 0.0}),
        ("fault", {"battery_soc_pct": 38.0, "mppt_state_label": "Fault", "pv_power_w": 0.0}),
    ],
)
def test_scenarios_return_expected_summary(client, name, expected):
    response = client.get(f"/api/solar/scenario?name={name}")
    data = response.get_json()
    assert response.status_code == 200
    assert data["data_available"] is True
    for key, value in expected.items():
        assert data[key] == value
    for key in ["battery_power_w", "mppt_state", "mppt_state_label", "pv_power_w"]:
        assert key in data


def test_unknown_scenario_returns_available_list(client):
    response = client.get("/api/solar/scenario?name=missing")
    data = response.get_json()
    assert response.status_code == 400
    assert data["error"] == "unknown scenario"
    assert data["available"] == sorted(dev_server.SCENARIOS)


def test_scenario_missing_name_returns_available_list(client):
    response = client.get("/api/solar/scenario")
    data = response.get_json()
    assert response.status_code == 400
    assert data["error"] == "unknown scenario"
    assert data["available"] == sorted(dev_server.SCENARIOS)
