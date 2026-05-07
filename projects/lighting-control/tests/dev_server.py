# dev_server.py — Lighting control UI development server
# Serves /api/lighting/* routes from pre-generated fixture files.
# Use for UI testing without InfluxDB or Shelly hardware.
#
# Run:  cd projects/lighting-control && python -m tests.dev_server
# Open: http://localhost:5005
#
# Switch UI states via the scenario endpoint:
#   GET /api/lighting/scenario?name=all_on
#   GET /api/lighting/scenario?name=all_off
#   GET /api/lighting/scenario?name=partial
#   GET /api/lighting/scenario?name=no_data
# Refresh the browser after each to see the state change.
#
# NOT for production use. Not covered by the test suite.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request


BASE_DIR = Path(__file__).resolve().parents[1]
FIXTURE_DIR = BASE_DIR / "tests" / "fixtures"
TEMPLATE_DIR = BASE_DIR / "dashboard" / "templates"

SCENARIOS = {
    "all_on": {"devices_on": 4, "devices_total": 4, "total_power_w": 180.0, "data_available": True},
    "all_off": {"devices_on": 0, "devices_total": 4, "total_power_w": 0.0, "data_available": True},
    "partial": {"devices_on": 2, "devices_total": 4, "total_power_w": 75.0, "data_available": True},
    "no_data": {"devices_on": None, "devices_total": 0, "total_power_w": None, "data_available": False},
}

app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
state: dict[str, Any] = {}


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def ensure_fixtures() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    overview = {
        "devices_total": 4,
        "devices_on": 2,
        "rooms_total": 3,
        "rooms_with_lights_on": 2,
        "total_power_w": 75.0,
        "data_available": True,
    }
    devices = [
        {"device_id": "living_room_main", "name": "Living Room Main", "room": "living_room", "device_type": "shellyplus1pm", "generation": "gen2", "is_on": True, "brightness_pct": None, "power_w": 42.5, "last_seen": "2026-05-07T10:00:00+00:00", "online": True},
        {"device_id": "bedroom_lamp", "name": "Bedroom Lamp", "room": "bedroom", "device_type": "shelly1", "generation": "gen1", "is_on": False, "brightness_pct": None, "power_w": None, "last_seen": "2026-05-07T10:00:00+00:00", "online": True},
        {"device_id": "kitchen_counter", "name": "Kitchen Counter", "room": "kitchen", "device_type": "shellydimmer2", "generation": "gen1", "is_on": True, "brightness_pct": 65.0, "power_w": 32.5, "last_seen": "2026-05-07T10:00:00+00:00", "online": True},
        {"device_id": "office_ceiling", "name": "Office Ceiling", "room": "office", "device_type": "shellyplus1", "generation": "gen2", "is_on": False, "brightness_pct": None, "power_w": 0.0, "last_seen": "2026-05-07T10:00:00+00:00", "online": True},
    ]
    rooms = [
        {"room_id": "living_room", "name": "Living Room", "devices_total": 1, "devices_on": 1, "total_power_w": 42.5},
        {"room_id": "bedroom", "name": "Bedroom", "devices_total": 1, "devices_on": 0, "total_power_w": 0.0},
        {"room_id": "kitchen", "name": "Kitchen", "devices_total": 1, "devices_on": 1, "total_power_w": 32.5},
        {"room_id": "office", "name": "Office", "devices_total": 1, "devices_on": 0, "total_power_w": 0.0},
    ]
    for name, data in {"overview.json": overview, "devices_state.json": devices, "rooms_summary.json": rooms}.items():
        path = FIXTURE_DIR / name
        if not path.exists():
            _write_json(path, data)


def load_fixtures() -> None:
    ensure_fixtures()
    state["overview"] = json.loads((FIXTURE_DIR / "overview.json").read_text(encoding="utf-8"))
    state["devices"] = json.loads((FIXTURE_DIR / "devices_state.json").read_text(encoding="utf-8"))
    state["rooms"] = json.loads((FIXTURE_DIR / "rooms_summary.json").read_text(encoding="utf-8"))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/lighting/scenario")
def scenario():
    name = request.args.get("name", "partial")
    if name not in SCENARIOS:
        return jsonify({"error": "unknown scenario", "available": sorted(SCENARIOS)}), 400
    selected = SCENARIOS[name]
    state["overview"].update(selected)
    if name == "all_on":
        for device in state["devices"]:
            device["is_on"] = True
            device["power_w"] = 45.0
    elif name == "all_off":
        for device in state["devices"]:
            device["is_on"] = False
            device["power_w"] = 0.0
    elif name == "no_data":
        state["devices"] = []
        state["rooms"] = []
    else:
        load_fixtures()
    return jsonify({"ok": True, "scenario": name})


@app.route("/api/lighting/overview")
def overview():
    return jsonify(state["overview"])


@app.route("/api/lighting/devices")
def devices():
    return jsonify(state["devices"])


@app.route("/api/lighting/devices/<device_id>")
def device(device_id: str):
    for item in state["devices"]:
        if item["device_id"] == device_id:
            return jsonify(item)
    return jsonify({"error": "device not found"}), 404


@app.route("/api/lighting/devices/<device_id>/set", methods=["POST"])
def set_device(device_id: str):
    for item in state["devices"]:
        if item["device_id"] == device_id:
            body = request.get_json(silent=True) or {}
            if "on" in body:
                item["is_on"] = bool(body["on"])
            if "brightness" in body:
                item["brightness_pct"] = float(body["brightness"])
            return jsonify({"ok": True})
    return jsonify({"error": "device not found"}), 404


@app.route("/api/lighting/rooms")
def rooms():
    return jsonify(state["rooms"])


@app.route("/api/lighting/history")
def history():
    if not request.args.get("device_id"):
        return jsonify({"error": "device not found"}), 404
    return jsonify([])


@app.route("/api/lighting/status")
def status():
    return jsonify({"mqtt_connected": True, "influxdb_ok": True, "device_count": len(state["devices"]), "data_available": bool(state["devices"]), "last_event_minutes_ago": 1.0})


load_fixtures()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005)
