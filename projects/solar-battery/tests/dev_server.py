# dev_server.py — Solar battery UI development server
# Serves /api/solar/* routes from pre-generated fixture files.
# Use for UI testing without InfluxDB or Cerbo GX hardware.
#
# Run:  cd projects/solar-battery && python -m tests.dev_server
# Open: http://localhost:5003
#
# Test UI states via the scenario endpoint:
#   GET /api/solar/scenario?name=low_battery
#   GET /api/solar/scenario?name=charging
#   GET /api/solar/scenario?name=cloudy
#   GET /api/solar/scenario?name=night
#   GET /api/solar/scenario?name=fault
# Refresh the dashboard after each to see the state change.
#
# NOT for production use. Not covered by the test suite.

from __future__ import annotations

import csv
import json
from pathlib import Path

from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = BASE_DIR / "fixtures"
TEMPLATE_DIR = BASE_DIR.parent / "dashboard" / "templates"

app = Flask(__name__, template_folder=str(TEMPLATE_DIR))

SCENARIOS = {
    "low_battery": {"battery_soc_pct": 12.5, "battery_power_w": -180.0,
                    "mppt_state": 0, "mppt_state_label": "Off",
                    "pv_power_w": 0.0},
    "charging":    {"battery_soc_pct": 67.0, "battery_power_w": 820.0,
                    "mppt_state": 3, "mppt_state_label": "Bulk",
                    "pv_power_w": 1050.0},
    "cloudy":      {"battery_soc_pct": 45.0, "battery_power_w": 95.0,
                    "mppt_state": 3, "mppt_state_label": "Bulk",
                    "pv_power_w": 180.0},
    "night":       {"battery_soc_pct": 55.0, "battery_power_w": -220.0,
                    "mppt_state": 0, "mppt_state_label": "Off",
                    "pv_power_w": 0.0},
    "fault":       {"battery_soc_pct": 38.0, "battery_power_w": 0.0,
                    "mppt_state": 2, "mppt_state_label": "Fault",
                    "pv_power_w": 0.0},
}


def load_json(name: str):
    with (FIXTURE_DIR / name).open() as f:
        return json.load(f)


def load_csv(name: str) -> list[dict]:
    with (FIXTURE_DIR / name).open(newline="") as f:
        return list(csv.DictReader(f))


def float_value(row: dict, key: str) -> float | None:
    value = row.get(key)
    return float(value) if value not in (None, "") else None


summary = load_json("solar_summary_latest.json")
battery_rows = load_json("battery_history.json")
energy_rows = load_csv("energy_totals.csv")
solar_rows = load_csv("solar_readings.csv")


@app.route("/")
def index():
    return render_template("index.html", system={}, battery={})


@app.route("/api/solar/summary")
def api_solar_summary():
    return jsonify(summary)


@app.route("/api/solar/battery")
def api_solar_battery():
    return jsonify(battery_rows)


@app.route("/api/solar/pv")
def api_solar_pv():
    return jsonify([
        {"date": row["date"], "yield_kwh": float_value(row, "pv_yield_kwh")}
        for row in energy_rows[-7:]
    ])


@app.route("/api/solar/history")
def api_solar_history():
    days = request.args.get("days", "30")
    try:
        count = int(days)
    except ValueError:
        return jsonify({"error": "invalid input"}), 400
    if count < 1 or count > 365:
        return jsonify({"error": "invalid input"}), 400
    rows = energy_rows[-count:]
    return jsonify([
        {
            "date": row["date"],
            "pv_yield_kwh": float_value(row, "pv_yield_kwh"),
            "grid_import_kwh": float_value(row, "grid_import_kwh"),
            "grid_export_kwh": float_value(row, "grid_export_kwh"),
            "avg_battery_soc_pct": float_value(row, "avg_battery_soc_pct"),
            "peak_pv_power_w": float_value(row, "peak_pv_power_w"),
        }
        for row in rows
    ])


@app.route("/api/solar/status")
def api_solar_status():
    return jsonify({
        "data_available": bool(summary.get("data_available")),
        "last_seen_minutes_ago": 1,
        "cerbo_online": True,
        "mppt_online": summary.get("mppt_state") not in (None, 0),
        "inverter_online": summary.get("inverter_output_w") is not None,
    })


@app.route("/api/solar/scenario")
def api_solar_scenario():
    name = request.args.get("name")
    if name not in SCENARIOS:
        return jsonify({"error": "unknown scenario", "available": sorted(SCENARIOS)}), 400
    summary.update(SCENARIOS[name])
    summary["data_available"] = True
    return jsonify(summary)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003)
