"""Water monitor UI development server backed by static fixtures.

Run from the water-monitor project directory:
  ../.venv/bin/python -m tests.dev_server

Open:
  http://127.0.0.1:5001
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = BASE_DIR / "fixtures"
TEMPLATE_DIR = BASE_DIR.parent / "dashboard" / "templates"
DEV_PORT = 5001

app = Flask(__name__, template_folder=str(TEMPLATE_DIR))

SCENARIOS: dict[str, dict[str, dict]] = {
    "normal": {},
    "low_tank1": {
        "tank1": {
            "level_pct": 18.0,
            "status": "low",
            "drain_rate_lph": 7.2,
            "days_remaining": 5.2,
        },
    },
    "low_both": {
        "tank1": {
            "level_pct": 12.0,
            "status": "critical",
            "drain_rate_lph": 7.8,
            "days_remaining": 3.2,
        },
        "tank2": {
            "level_pct": 13.0,
            "status": "critical",
            "drain_rate_lph": 14.0,
            "days_remaining": 5.7,
        },
    },
    "filling": {
        "tank1": {
            "level_pct": 66.0,
            "status": "filling",
            "drain_rate_lph": -45.0,
            "days_remaining": None,
            "pump": {"state": "running", "runtime_today_min": 44, "last_seen_min": 1},
        },
    },
    "full": {
        "tank1": {
            "level_pct": 96.0,
            "status": "full",
            "drain_rate_lph": 1.4,
            "days_remaining": 142.9,
        },
        "tank2": {
            "level_pct": 97.0,
            "status": "full",
            "drain_rate_lph": 2.0,
            "days_remaining": 297.2,
        },
    },
    "sensor_offline": {
        "tank1": {
            "status": "stale",
            "sensor": {"last_seen_min": 95},
        },
        "tank2": {
            "status": "stale",
            "sensor": {"last_seen_min": 88},
        },
    },
}


def load_json(name: str):
    with (FIXTURE_DIR / name).open() as fixture:
        return json.load(fixture)


def _deep_update(target: dict, updates: dict) -> dict:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
    return target


def _set_level(tank: dict, level_pct: float) -> None:
    tank["level_pct"] = level_pct
    tank["volume_liters"] = round(tank["capacity_liters"] * level_pct / 100, 1)
    tank["water_depth_cm"] = round(tank["depth_cm"] * level_pct / 100, 1)


def _with_dashboard_fields(tank: dict) -> dict:
    enriched = copy.deepcopy(tank)
    enriched["reading"] = {
        "time": enriched["last_updated"],
        "level_pct": enriched["level_pct"],
        "volume_liters": enriched["volume_liters"],
        "level_cm": enriched["water_depth_cm"],
        "usable_depth_cm": enriched["depth_cm"],
        "capacity_liters": enriched["capacity_liters"],
    }
    enriched["rate_lph"] = enriched["drain_rate_lph"]
    enriched["days_left"] = enriched["days_remaining"]
    enriched["today_consumption_l"] = enriched["todays_use_liters"]
    enriched["avg_consumption_l"] = enriched["avg_consumption_liters"]
    return enriched


def build_scenario(name: str) -> list[dict]:
    if name not in SCENARIOS:
        raise KeyError(name)

    tanks = copy.deepcopy(load_json("tanks_normal.json"))
    by_id = {tank["id"]: tank for tank in tanks}
    for tank_id, updates in SCENARIOS[name].items():
        tank = by_id[tank_id]
        if "level_pct" in updates:
            _set_level(tank, updates["level_pct"])
        _deep_update(tank, updates)
    return [_with_dashboard_fields(tank) for tank in tanks]


current_tanks = build_scenario("normal")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/tanks")
def api_tanks():
    return jsonify(current_tanks)


@app.route("/api/history/<tank_id>")
def api_history(tank_id: str):
    fixture_name = {
        "tank1": "level_history_tank1.json",
        "tank2": "level_history_tank2.json",
    }.get(tank_id)
    if fixture_name is None:
        return jsonify({"error": "tank not found"}), 404
    return jsonify(load_json(fixture_name))


@app.route("/api/consumption")
def api_consumption():
    days_raw = request.args.get("days", "90")
    try:
        days = int(days_raw)
    except ValueError:
        return jsonify({"error": "invalid input"}), 400
    if days < 1 or days > 365:
        return jsonify({"error": "invalid input"}), 400
    return jsonify(load_json("consumption_history.json")[-days:])


@app.route("/api/source/<tank_id>", methods=["POST"])
def api_source(tank_id: str):
    data = request.get_json(silent=True) or {}
    source = data.get("source", "")
    tank = next((item for item in current_tanks if item["id"] == tank_id), None)
    if tank is None:
        return jsonify({"error": "tank not found"}), 404
    if source not in tank["sources"]:
        return jsonify({"error": "invalid source"}), 400
    tank["active_source"] = source
    return jsonify({"tank_id": tank_id, "active_source": source})


@app.route("/api/water/scenario")
def api_water_scenario():
    name = request.args.get("name", "")
    if name not in SCENARIOS:
        return jsonify({"error": "unknown scenario", "available": sorted(SCENARIOS)}), 400

    global current_tanks
    current_tanks = build_scenario(name)
    return jsonify(current_tanks)


if __name__ == "__main__":
    app.logger.warning(
        "Water monitor dev server on port %s. Scenarios: %s",
        DEV_PORT,
        ", ".join(sorted(SCENARIOS)),
    )
    app.run(host="0.0.0.0", port=DEV_PORT)
