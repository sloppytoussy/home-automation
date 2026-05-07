from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from dashboard import app as solar_app


@pytest.fixture
def client():
    solar_app.app.config.update(TESTING=True)
    return solar_app.app.test_client()


def sample_row(**overrides):
    row = {
        "time": datetime.now(timezone.utc),
        "device": "cerbo",
        "portal_id": None,
        "source": "victron_cerbo",
        "pv_power_w": 820.0,
        "pv_yield_today_kwh": 4.2,
        "battery_soc_pct": 66.5,
        "battery_power_w": 220.0,
        "battery_voltage_v": 25.1,
        "battery_current_a": 8.8,
        "grid_power_w": -120.0,
        "ac_load_w": 610.0,
        "inverter_output_w": 600.0,
        "mppt_state": 3,
    }
    row.update(overrides)
    return row


def mock_latest(monkeypatch, row):
    monkeypatch.setattr(solar_app, "latest_solar_reading", lambda: row)


def mock_error(monkeypatch, func_name):
    def raise_error():
        raise RuntimeError("boom")

    monkeypatch.setattr(solar_app, func_name, raise_error)


@pytest.mark.parametrize(
    ("state", "label"),
    [
        (0, "Off"),
        (2, "Fault"),
        (3, "Bulk"),
        (4, "Absorption"),
        (5, "Float"),
        (99, "Unknown"),
    ],
)
def test_summary_mppt_state_labels(client, monkeypatch, state, label):
    mock_latest(monkeypatch, sample_row(mppt_state=state))
    response = client.get("/api/solar/summary")
    assert response.status_code == 200
    assert response.get_json()["mppt_state_label"] == label


def test_summary_happy_path_returns_all_fields(client, monkeypatch):
    mock_latest(monkeypatch, sample_row())
    response = client.get("/api/solar/summary")
    data = response.get_json()
    assert response.status_code == 200
    assert data["data_available"] is True
    assert data["pv_power_w"] == 820.0
    assert data["battery_soc_pct"] == 66.5
    assert data["grid_power_w"] == -120.0
    assert data["ac_load_w"] == 610.0
    assert data["mppt_state_label"] == "Bulk"


def test_summary_no_data_returns_placeholder(client, monkeypatch):
    mock_latest(monkeypatch, None)
    response = client.get("/api/solar/summary")
    data = response.get_json()
    assert response.status_code == 200
    assert data["data_available"] is False
    assert data["pv_power_w"] is None
    assert data["battery_soc_pct"] is None
    assert data["mppt_state"] is None


def test_summary_influxdb_unavailable(client, monkeypatch):
    mock_error(monkeypatch, "latest_solar_reading")
    response = client.get("/api/solar/summary")
    assert response.status_code == 503
    assert response.get_json() == {"error": "InfluxDB unavailable"}


def test_battery_happy_path(client, monkeypatch):
    rows = [{
        "time": "2026-05-06T00:00:00+00:00",
        "soc_pct": 50.0,
        "power_w": -100.0,
        "voltage_v": 24.2,
        "current_a": -4.1,
    }]
    monkeypatch.setattr(solar_app, "battery_history", lambda: rows)
    response = client.get("/api/solar/battery")
    assert response.status_code == 200
    assert response.get_json() == rows


def test_battery_empty(client, monkeypatch):
    monkeypatch.setattr(solar_app, "battery_history", lambda: [])
    response = client.get("/api/solar/battery")
    assert response.status_code == 200
    assert response.get_json() == []


def test_battery_influxdb_unavailable(client, monkeypatch):
    mock_error(monkeypatch, "battery_history")
    response = client.get("/api/solar/battery")
    assert response.status_code == 503
    assert response.get_json() == {"error": "InfluxDB unavailable"}


def test_pv_happy_path(client, monkeypatch):
    rows = [{"date": "2026-05-06", "yield_kwh": 6.1}]
    monkeypatch.setattr(solar_app, "pv_yield_history", lambda: rows)
    response = client.get("/api/solar/pv")
    assert response.status_code == 200
    assert response.get_json() == rows


def test_pv_partial_data(client, monkeypatch):
    rows = [{"date": "2026-05-06", "yield_kwh": None}]
    monkeypatch.setattr(solar_app, "pv_yield_history", lambda: rows)
    response = client.get("/api/solar/pv")
    assert response.status_code == 200
    assert response.get_json()[0]["yield_kwh"] is None


def test_pv_influxdb_unavailable(client, monkeypatch):
    mock_error(monkeypatch, "pv_yield_history")
    response = client.get("/api/solar/pv")
    assert response.status_code == 503
    assert response.get_json() == {"error": "InfluxDB unavailable"}


def history_rows():
    return [{
        "date": "2026-05-06",
        "pv_yield_kwh": 6.1,
        "grid_import_kwh": 0.0,
        "grid_export_kwh": 0.2,
        "avg_battery_soc_pct": 48.0,
        "peak_pv_power_w": 850.0,
    }]


def test_history_default_days(client, monkeypatch):
    seen = {}

    def fake_history(days):
        seen["days"] = days
        return history_rows()

    monkeypatch.setattr(solar_app, "daily_energy_history", fake_history)
    response = client.get("/api/solar/history")
    assert response.status_code == 200
    assert seen["days"] == 30
    assert response.get_json() == history_rows()


def test_history_custom_days(client, monkeypatch):
    seen = {}

    def fake_history(days):
        seen["days"] = days
        return history_rows()

    monkeypatch.setattr(solar_app, "daily_energy_history", fake_history)
    response = client.get("/api/solar/history?days=90")
    assert response.status_code == 200
    assert seen["days"] == 90


@pytest.mark.parametrize("days", ["0", "-1", "abc"])
def test_history_invalid_days(client, days):
    response = client.get(f"/api/solar/history?days={days}")
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid input"}


def test_history_days_above_max(client):
    response = client.get("/api/solar/history?days=366")
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid input"}


def test_history_influxdb_unavailable(client, monkeypatch):
    def raise_error(days):
        raise RuntimeError("boom")

    monkeypatch.setattr(solar_app, "daily_energy_history", raise_error)
    response = client.get("/api/solar/history")
    assert response.status_code == 503
    assert response.get_json() == {"error": "InfluxDB unavailable"}


def test_status_fresh_data(client, monkeypatch):
    mock_latest(monkeypatch, sample_row(time=datetime.now(timezone.utc)))
    response = client.get("/api/solar/status")
    data = response.get_json()
    assert response.status_code == 200
    assert data["data_available"] is True
    assert data["cerbo_online"] is True
    assert data["inverter_online"] is True


def test_status_stale_data(client, monkeypatch):
    mock_latest(monkeypatch, sample_row(time=datetime.now(timezone.utc) - timedelta(minutes=10)))
    response = client.get("/api/solar/status")
    data = response.get_json()
    assert response.status_code == 200
    assert data["cerbo_online"] is False
    assert data["mppt_online"] is False


def test_status_mppt_state_off(client, monkeypatch):
    mock_latest(monkeypatch, sample_row(mppt_state=0))
    response = client.get("/api/solar/status")
    data = response.get_json()
    assert response.status_code == 200
    assert data["cerbo_online"] is True
    assert data["mppt_online"] is False


def test_status_mppt_state_bulk(client, monkeypatch):
    mock_latest(monkeypatch, sample_row(mppt_state=3))
    response = client.get("/api/solar/status")
    data = response.get_json()
    assert response.status_code == 200
    assert data["cerbo_online"] is True
    assert data["mppt_online"] is True


def test_status_no_data(client, monkeypatch):
    mock_latest(monkeypatch, None)
    response = client.get("/api/solar/status")
    assert response.status_code == 200
    assert response.get_json() == {
        "data_available": False,
        "last_seen_minutes_ago": None,
        "cerbo_online": False,
        "mppt_online": False,
        "inverter_online": False,
    }


def test_status_influxdb_unavailable(client, monkeypatch):
    mock_error(monkeypatch, "latest_solar_reading")
    response = client.get("/api/solar/status")
    assert response.status_code == 503
    assert response.get_json() == {"error": "InfluxDB unavailable"}


def test_battery_history_maps_query_rows(monkeypatch):
    row = sample_row()
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", lambda flux: [row])
    assert solar_app.battery_history()[0] == {
        "time": solar_app.iso_time(row["time"]),
        "soc_pct": 66.5,
        "power_w": 220.0,
        "voltage_v": 25.1,
        "current_a": 8.8,
    }


def test_battery_history_empty_without_bucket(monkeypatch):
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: None)
    assert solar_app.battery_history() == []


def test_pv_yield_history_maps_query_rows(monkeypatch):
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", lambda flux: [{
        "time": datetime(2026, 5, 6, tzinfo=timezone.utc),
        "pv_yield_today_kwh": 6.18,
    }])
    assert solar_app.pv_yield_history() == [{"date": "2026-05-06", "yield_kwh": 6.18}]


def test_pv_yield_history_empty_without_bucket(monkeypatch):
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: None)
    assert solar_app.pv_yield_history() == []


def test_daily_energy_history_maps_query_rows(monkeypatch):
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", lambda flux: [{
        "time": datetime(2026, 5, 6, tzinfo=timezone.utc),
        "pv_yield_kwh": 6.18,
        "grid_import_kwh": 0.0,
        "grid_export_kwh": 0.4,
        "avg_battery_soc_pct": 47.5,
        "peak_pv_power_w": 850.0,
    }])
    assert solar_app.daily_energy_history(30) == [{
        "date": "2026-05-06",
        "pv_yield_kwh": 6.18,
        "grid_import_kwh": 0.0,
        "grid_export_kwh": 0.4,
        "avg_battery_soc_pct": 47.5,
        "peak_pv_power_w": 850.0,
    }]


def test_daily_energy_history_empty_without_bucket(monkeypatch):
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: None)
    assert solar_app.daily_energy_history(30) == []


def test_legacy_live_returns_solar_summary(client, monkeypatch):
    mock_latest(monkeypatch, sample_row())
    response = client.get("/api/live")
    assert response.status_code == 200
    assert response.get_json()["data_available"] is True


def test_legacy_history_unknown_field(client):
    response = client.get("/api/history/unknown")
    assert response.status_code == 400
    assert response.get_json() == {"error": "unknown field"}


def test_legacy_history_invalid_hours(client):
    response = client.get("/api/history/pv_power_w?hours=0")
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid input"}


def test_legacy_yield_returns_pv_shape(client, monkeypatch):
    monkeypatch.setattr(solar_app, "pv_yield_history", lambda: [{"date": "2026-05-06", "yield_kwh": 6.1}])
    response = client.get("/api/yield")
    assert response.status_code == 200
    assert response.get_json() == [{"time": "2026-05-06", "value": 6.1}]


def test_minutes_since_accepts_iso_string():
    minutes = solar_app.minutes_since((datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat())
    assert 1 <= minutes <= 3


def test_normalize_summary_accepts_string_state():
    data = solar_app.normalize_summary(sample_row(mppt_state="4"))
    assert data["mppt_state_label"] == "Absorption"


def test_normalize_summary_handles_missing_optional_tags():
    data = solar_app.normalize_summary({"time": "2026-05-06T00:00:00+00:00", "pv_power_w": 1.0})
    assert data["data_available"] is True
    assert data["device"] is None
    assert data["battery_soc_pct"] is None


def test_solar_status_without_inverter_output_is_not_inverter_online():
    data = solar_app.solar_status(sample_row(inverter_output_w=None))
    assert data["cerbo_online"] is True
    assert data["inverter_online"] is False


def test_index_route_returns_dashboard_html(client, monkeypatch):
    monkeypatch.setattr(solar_app, "load_config", lambda: {"system": {}, "battery": {}})
    response = client.get("/")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Solar Battery Dashboard" in body
    assert "/api/solar/summary" in body
    assert 'id="root"' in body


def test_index_route_handles_missing_config(client, monkeypatch):
    monkeypatch.setattr(solar_app, "load_config", lambda: {})
    response = client.get("/")
    assert response.status_code == 200
    assert "Waiting for Cerbo GX" in response.get_data(as_text=True)


def test_live_valid_mock_data(client, monkeypatch):
    mock_latest(monkeypatch, sample_row(pv_power_w=455.0))
    response = client.get("/api/live")
    assert response.status_code == 200
    assert response.get_json()["pv_power_w"] == 455.0


def test_live_empty_result(client, monkeypatch):
    mock_latest(monkeypatch, None)
    response = client.get("/api/live")
    data = response.get_json()
    assert response.status_code == 200
    assert data["data_available"] is False
    assert data["pv_power_w"] is None


def test_live_influx_unavailable(client, monkeypatch):
    mock_error(monkeypatch, "latest_solar_reading")
    response = client.get("/api/live")
    assert response.status_code == 503
    assert response.get_json() == {"error": "InfluxDB unavailable"}


@pytest.mark.parametrize(
    ("route_field", "query_field"),
    [
        ("pv_power", "pv_power_w"),
        ("battery_voltage", "battery_voltage_v"),
        ("battery_soc", "battery_soc_pct"),
        ("load_power", "ac_load_w"),
        ("pv_power_w", "pv_power_w"),
        ("battery_power_w", "battery_power_w"),
        ("grid_power_w", "grid_power_w"),
        ("inverter_output_w", "inverter_output_w"),
    ],
)
def test_legacy_history_valid_fields(client, monkeypatch, route_field, query_field):
    captured = {}

    def fake_query(flux):
        captured["flux"] = flux
        return [{
            "time": datetime(2026, 5, 6, tzinfo=timezone.utc),
            query_field: 123.4,
        }]

    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", fake_query)
    response = client.get(f"/api/history/{route_field}")
    assert response.status_code == 200
    assert response.get_json() == [{"time": "2026-05-06T00:00:00+00:00", "value": 123.4}]
    assert f'r._field == "{query_field}"' in captured["flux"]


@pytest.mark.parametrize("field", ["unknown", "daily_yield_kwh", "battery_voltage"])
def test_legacy_history_invalid_or_unmapped_field_returns_400_or_404(client, field):
    route = field if field != "battery_voltage" else "battery_voltage_extra"
    response = client.get(f"/api/history/{route}")
    assert response.status_code in (400, 404)
    if response.status_code == 400:
        assert response.get_json() == {"error": "unknown field"}


@pytest.mark.parametrize("hours", [1, 24, 168])
def test_legacy_history_hours_boundaries(client, monkeypatch, hours):
    captured = {}

    def fake_query(flux):
        captured["flux"] = flux
        return []

    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", fake_query)
    response = client.get(f"/api/history/pv_power?hours={hours}")
    assert response.status_code == 200
    assert f"range(start: -{hours}h)" in captured["flux"]


@pytest.mark.parametrize("hours", [169, 0, -1, "abc"])
def test_legacy_history_invalid_hours_returns_400(client, hours):
    response = client.get(f"/api/history/pv_power?hours={hours}")
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid input"}


def test_legacy_history_missing_bucket_returns_empty(client, monkeypatch):
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: None)
    response = client.get("/api/history/pv_power?hours=24")
    assert response.status_code == 200
    assert response.get_json() == []


def test_legacy_history_influx_unavailable(client, monkeypatch):
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")

    def raise_error(flux):
        raise RuntimeError("boom")

    monkeypatch.setattr(solar_app, "query_pivot", raise_error)
    response = client.get("/api/history/pv_power?hours=24")
    assert response.status_code == 503
    assert response.get_json() == {"error": "InfluxDB unavailable"}


def test_yield_happy_path(client, monkeypatch):
    monkeypatch.setattr(solar_app, "pv_yield_history", lambda: [{"date": "2026-05-06", "yield_kwh": 7.2}])
    response = client.get("/api/yield")
    assert response.status_code == 200
    assert response.get_json() == [{"time": "2026-05-06", "value": 7.2}]


def test_yield_empty_rows(client, monkeypatch):
    monkeypatch.setattr(solar_app, "pv_yield_history", lambda: [])
    response = client.get("/api/yield")
    assert response.status_code == 200
    assert response.get_json() == []


def test_yield_influx_unavailable(client, monkeypatch):
    mock_error(monkeypatch, "pv_yield_history")
    response = client.get("/api/yield")
    assert response.status_code == 503
    assert response.get_json() == {"error": "InfluxDB unavailable"}


@pytest.mark.parametrize("days", [1, 7, 30, 90])
def test_daily_energy_history_day_ranges(monkeypatch, days):
    captured = {}

    def fake_query(flux):
        captured["flux"] = flux
        return []

    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", fake_query)
    assert solar_app.daily_energy_history(days) == []
    assert f"range(start: -{days}d)" in captured["flux"]


def test_daily_energy_history_field_mapping_completeness(monkeypatch):
    row = {
        "time": datetime(2026, 5, 7, tzinfo=timezone.utc),
        "pv_yield_kwh": 8.0,
        "grid_import_kwh": 1.2,
        "grid_export_kwh": 0.5,
        "avg_battery_soc_pct": 61.0,
        "peak_pv_power_w": 1001.0,
    }
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", lambda flux: [row])
    assert solar_app.daily_energy_history(7)[0] == {
        "date": "2026-05-07",
        "pv_yield_kwh": 8.0,
        "grid_import_kwh": 1.2,
        "grid_export_kwh": 0.5,
        "avg_battery_soc_pct": 61.0,
        "peak_pv_power_w": 1001.0,
    }


def test_daily_energy_history_empty_rows_returns_empty(monkeypatch):
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", lambda flux: [])
    assert solar_app.daily_energy_history(30) == []


def test_battery_history_null_fields_stay_null(monkeypatch):
    row = {
        "time": datetime(2026, 5, 7, tzinfo=timezone.utc),
        "battery_soc_pct": None,
        "battery_power_w": None,
        "battery_voltage_v": None,
        "battery_current_a": None,
    }
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", lambda flux: [row])
    result = solar_app.battery_history()[0]
    assert result["soc_pct"] is None
    assert result["power_w"] is None
    assert result["voltage_v"] is None
    assert result["current_a"] is None


def test_battery_history_returns_all_query_rows(monkeypatch):
    rows = [
        sample_row(time=datetime(2026, 5, 7, hour=i, tzinfo=timezone.utc), battery_soc_pct=float(i))
        for i in range(6)
    ]
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", lambda flux: rows)
    result = solar_app.battery_history()
    assert len(result) == 6
    assert result[0]["soc_pct"] == 0.0
    assert result[-1]["soc_pct"] == 5.0


def test_battery_history_uses_24_hour_window(monkeypatch):
    captured = {}

    def fake_query(flux):
        captured["flux"] = flux
        return []

    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", fake_query)
    assert solar_app.battery_history() == []
    assert "range(start: -24h)" in captured["flux"]


def test_pv_yield_history_null_fields_stay_null(monkeypatch):
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", lambda flux: [{
        "time": datetime(2026, 5, 7, tzinfo=timezone.utc),
        "pv_yield_today_kwh": None,
    }])
    assert solar_app.pv_yield_history() == [{"date": "2026-05-07", "yield_kwh": None}]


def test_pv_yield_history_returns_all_query_rows(monkeypatch):
    rows = [
        {"time": datetime(2026, 5, day, tzinfo=timezone.utc), "pv_yield_today_kwh": float(day)}
        for day in range(1, 8)
    ]
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", lambda flux: rows)
    result = solar_app.pv_yield_history()
    assert len(result) == 7
    assert result[0] == {"date": "2026-05-01", "yield_kwh": 1.0}
    assert result[-1] == {"date": "2026-05-07", "yield_kwh": 7.0}


def test_pv_yield_history_uses_7_day_window(monkeypatch):
    captured = {}

    def fake_query(flux):
        captured["flux"] = flux
        return []

    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", fake_query)
    assert solar_app.pv_yield_history() == []
    assert "range(start: -7d)" in captured["flux"]


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (4, True),
        (16, False),
    ],
)
def test_solar_status_fresh_and_stale_boundaries(minutes, expected):
    row = sample_row(time=datetime.now(timezone.utc) - timedelta(minutes=minutes))
    assert solar_app.solar_status(row)["cerbo_online"] is expected


def test_solar_status_exactly_five_minutes_is_stale(monkeypatch):
    monkeypatch.setattr(solar_app, "minutes_since", lambda value: 5.0)
    data = solar_app.solar_status(sample_row())
    assert data["cerbo_online"] is False
    assert data["mppt_online"] is False
    assert data["inverter_online"] is False


@pytest.mark.parametrize(
    ("inverter_output", "expected"),
    [
        (6.0, True),
        (-6.0, True),
        (4.9, False),
        (0.0, False),
        (None, False),
    ],
)
def test_solar_status_inverter_power_threshold(inverter_output, expected):
    data = solar_app.solar_status(sample_row(inverter_output_w=inverter_output))
    assert data["inverter_online"] is expected


def test_solar_status_none_row_input():
    assert solar_app.solar_status(None) == {
        "data_available": False,
        "last_seen_minutes_ago": None,
        "cerbo_online": False,
        "mppt_online": False,
        "inverter_online": False,
    }


@pytest.mark.parametrize(
    ("state", "label"),
    [
        (3.0, "Bulk"),
        (3, "Bulk"),
        (2.0, "Fault"),
    ],
)
def test_normalize_summary_state_numeric_inputs(state, label):
    assert solar_app.normalize_summary(sample_row(mppt_state=state))["mppt_state_label"] == label


def test_normalize_summary_all_optional_fields_missing():
    data = solar_app.normalize_summary({"time": "2026-05-07T01:02:03+00:00"})
    assert data["data_available"] is True
    for field in solar_app.SOLAR_FIELDS:
        assert data[field] is None
    assert data["device"] is None
    assert data["portal_id"] is None


def test_normalize_summary_all_fields_present():
    row = sample_row(portal_id="portal-from-fixture")
    data = solar_app.normalize_summary(row)
    for key, value in row.items():
        if key == "time":
            assert data[key] == solar_app.iso_time(value)
        else:
            assert data[key] == value
    assert data["last_updated"] == data["time"]


@pytest.mark.parametrize("value", [None])
def test_iso_time_none_input_returns_none(value):
    assert solar_app.iso_time(value) is None


def test_iso_time_valid_iso_string():
    assert solar_app.iso_time("2026-05-07T01:02:03+00:00") == "2026-05-07T01:02:03+00:00"


def test_iso_time_invalid_string_returns_none():
    assert solar_app.iso_time("not-a-date") is None


def test_iso_time_datetime_input():
    value = datetime(2026, 5, 7, 1, 2, 3, tzinfo=timezone.utc)
    assert solar_app.iso_time(value) == "2026-05-07T01:02:03+00:00"


@pytest.mark.parametrize("value", [None])
def test_date_value_none_input_returns_none(value):
    assert solar_app.date_value(value) is None


def test_date_value_valid_iso_string():
    assert solar_app.date_value("2026-05-07T01:02:03+00:00") == "2026-05-07"


def test_date_value_invalid_string_returns_none():
    assert solar_app.date_value("not-a-date") is None


def test_date_value_datetime_input():
    value = datetime(2026, 5, 7, 1, 2, 3, tzinfo=timezone.utc)
    assert solar_app.date_value(value) == "2026-05-07"


def test_load_config_missing_file_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(solar_app, "CONFIG_PATH", tmp_path / "missing.yaml")
    assert solar_app.load_config() == {}


def test_load_config_malformed_yaml_returns_empty(monkeypatch, tmp_path):
    config_path = tmp_path / "bad.yaml"
    config_path.write_text("system: [unterminated\n")
    monkeypatch.setattr(solar_app, "CONFIG_PATH", config_path)
    assert solar_app.load_config() == {}


def test_load_config_valid_yaml(monkeypatch, tmp_path):
    config_path = tmp_path / "inverter.yaml"
    config_path.write_text("system:\n  name: Solar\nbattery:\n  min_soc_pct: 20\n")
    monkeypatch.setattr(solar_app, "CONFIG_PATH", config_path)
    assert solar_app.load_config() == {"system": {"name": "Solar"}, "battery": {"min_soc_pct": 20}}


def test_influx_bucket_with_required_env(monkeypatch):
    for name in solar_app.INFLUX_REQUIRED_ENV:
        monkeypatch.setenv(name, "value")
    monkeypatch.setenv("INFLUXDB_BUCKET", "solar")
    assert solar_app.influx_bucket() == "solar"


def test_influx_bucket_unset_bucket(monkeypatch):
    for name in solar_app.INFLUX_REQUIRED_ENV:
        monkeypatch.setenv(name, "value")
    monkeypatch.delenv("INFLUXDB_BUCKET", raising=False)
    assert solar_app.influx_bucket() is None


@pytest.mark.parametrize("missing", list(solar_app.INFLUX_REQUIRED_ENV))
def test_influx_bucket_missing_any_required_env(monkeypatch, missing):
    for name in solar_app.INFLUX_REQUIRED_ENV:
        monkeypatch.setenv(name, "value")
    monkeypatch.delenv(missing, raising=False)
    assert solar_app.influx_bucket() is None


def test_latest_solar_reading_empty_rows(monkeypatch):
    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", lambda flux: [])
    assert solar_app.latest_solar_reading() is None


def test_latest_solar_reading_uses_30_day_window(monkeypatch):
    captured = {}
    row = sample_row()

    def fake_query(flux):
        captured["flux"] = flux
        return [row]

    monkeypatch.setattr(solar_app, "influx_bucket", lambda: "solar")
    monkeypatch.setattr(solar_app, "query_pivot", fake_query)
    assert solar_app.latest_solar_reading() == row
    assert "range(start: -30d)" in captured["flux"]
