from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.app import app

TIERS = [
    {"name": "lifeline", "start_kwh": 0, "end_kwh": 20, "rate_rwf_per_kwh": 89},
    {"name": "standard", "start_kwh": 20, "end_kwh": 50, "rate_rwf_per_kwh": 310},
    {"name": "high_usage", "start_kwh": 50, "end_kwh": None, "rate_rwf_per_kwh": 369},
]


@pytest.fixture
def client():
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.mark.parametrize(
    "payload,expected_cost",
    [
        ({"kwh": 0}, 0),
        ({"kwh": 10}, 890),
        ({"kwh": 20}, 1780),
        ({"kwh": 25}, 3330),
        ({"kwh": 60}, 14770),
    ],
)
def test_bill_estimate_returns_tiered_cost(client, payload, expected_cost):
    with patch("dashboard.app.calculator_tiers", return_value=TIERS):
        response = client.post("/api/calculator/bill-estimate", json=payload)
    assert response.status_code == 200
    assert response.get_json()["total_cost_rwf"] == expected_cost


@pytest.mark.parametrize("payload", [{}, {"kwh": -1}, {"kwh": "bad"}])
def test_bill_estimate_bad_input_returns_400(client, payload):
    with patch("dashboard.app.calculator_tiers", return_value=TIERS):
        response = client.post("/api/calculator/bill-estimate", json=payload)
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_net_consumption_queries_energy_totals(client):
    with patch("dashboard.app.influx_bucket", return_value="bucket"), patch(
        "dashboard.app.query_pivot",
        return_value=[{"consumed_kwh": 15, "solar_export_kwh": 3}],
    ) as query_pivot:
        response = client.get("/api/calculator/net-consumption")
    assert response.status_code == 200
    assert response.get_json()["net_kwh"] == 12
    assert "energy_totals" in query_pivot.call_args.args[0]


def test_net_consumption_defaults_solar_export_to_zero(client):
    with patch("dashboard.app.influx_bucket", return_value="bucket"), patch(
        "dashboard.app.query_pivot", return_value=[{"consumed_kwh": 7}]
    ):
        response = client.get("/api/calculator/net-consumption")
    assert response.status_code == 200
    assert response.get_json()["solar_export_kwh"] == 0


def test_net_consumption_no_influx_returns_503(client):
    with patch("dashboard.app.influx_bucket", return_value=None):
        response = client.get("/api/calculator/net-consumption")
    assert response.status_code == 503


def test_net_consumption_query_failure_returns_503(client):
    with patch("dashboard.app.influx_bucket", return_value="bucket"), patch(
        "dashboard.app.query_pivot", side_effect=RuntimeError("down")
    ):
        response = client.get("/api/calculator/net-consumption")
    assert response.status_code == 503


def test_load_breakdown_returns_sorted_rows(client):
    with patch("dashboard.app.influx_bucket", return_value="bucket"), patch(
        "dashboard.app.query_pivot",
        return_value=[{"circuit": "a", "watts": 100}, {"circuit": "b", "watts": 300}],
    ):
        response = client.get("/api/calculator/load-breakdown")
    assert response.status_code == 200
    assert [row["circuit"] for row in response.get_json()] == ["b", "a"]


def test_load_breakdown_no_influx_returns_503(client):
    with patch("dashboard.app.influx_bucket", return_value=None):
        response = client.get("/api/calculator/load-breakdown")
    assert response.status_code == 503


def test_load_breakdown_query_failure_returns_503(client):
    with patch("dashboard.app.influx_bucket", return_value="bucket"), patch(
        "dashboard.app.query_pivot", side_effect=RuntimeError("down")
    ):
        response = client.get("/api/calculator/load-breakdown")
    assert response.status_code == 503


def test_load_breakdown_bad_influx_row_returns_400(client):
    with patch("dashboard.app.influx_bucket", return_value="bucket"), patch(
        "dashboard.app.query_pivot", return_value=[{"watts": 100}]
    ):
        response = client.get("/api/calculator/load-breakdown")
    assert response.status_code == 400


@pytest.mark.parametrize(
    "query,flagged",
    [
        ("manual_kwh=100&automated_kwh=101", False),
        ("manual_kwh=100&automated_kwh=103", True),
        ("manual_kwh=100&automated_kwh=97&threshold_pct=5", False),
    ],
)
def test_variance_query_args_return_result_without_influx(client, query, flagged):
    with patch("dashboard.app.influx_bucket") as bucket:
        response = client.get(f"/api/calculator/variance?{query}")
    assert response.status_code == 200
    assert response.get_json()["flagged"] is flagged
    bucket.assert_not_called()


@pytest.mark.parametrize("query", ["manual_kwh=0&automated_kwh=1", "manual_kwh=bad&automated_kwh=1", "manual_kwh=1&automated_kwh=-1"])
def test_variance_bad_query_args_return_400(client, query):
    response = client.get(f"/api/calculator/variance?{query}")
    assert response.status_code == 400


def test_variance_queries_verification_log_when_args_missing(client):
    with patch("dashboard.app.influx_bucket", return_value="bucket"), patch(
        "dashboard.app.query_pivot", return_value=[{"manual_kwh": 100, "automated_kwh": 104}]
    ) as query_pivot:
        response = client.get("/api/calculator/variance")
    assert response.status_code == 200
    assert response.get_json()["flagged"] is True
    assert "verification_log" in query_pivot.call_args.args[0]


def test_variance_no_influx_returns_503(client):
    with patch("dashboard.app.influx_bucket", return_value=None):
        response = client.get("/api/calculator/variance")
    assert response.status_code == 503


def test_variance_no_rows_returns_503(client):
    with patch("dashboard.app.influx_bucket", return_value="bucket"), patch("dashboard.app.query_pivot", return_value=[]):
        response = client.get("/api/calculator/variance")
    assert response.status_code == 503


def test_variance_query_failure_returns_503(client):
    with patch("dashboard.app.influx_bucket", return_value="bucket"), patch(
        "dashboard.app.query_pivot", side_effect=RuntimeError("down")
    ):
        response = client.get("/api/calculator/variance")
    assert response.status_code == 503


@pytest.mark.parametrize(
    "payload,confidence",
    [
        ({"daily_kwh": [1, 2, 3], "days_in_month": 30}, "low"),
        ({"daily_kwh": [1, 2, 3, 4, 5], "days_in_month": 30}, "medium"),
        ({"daily_kwh": [1] * 15, "days_in_month": 30}, "high"),
    ],
)
def test_projection_returns_monthly_projection(client, payload, confidence):
    response = client.post("/api/calculator/projection", json=payload)
    assert response.status_code == 200
    assert response.get_json()["confidence"] == confidence


@pytest.mark.parametrize("payload", [{}, {"daily_kwh": []}, {"daily_kwh": [-1]}, {"daily_kwh": [1], "days_in_month": 32}])
def test_projection_bad_input_returns_400(client, payload):
    response = client.post("/api/calculator/projection", json=payload)
    assert response.status_code == 400
