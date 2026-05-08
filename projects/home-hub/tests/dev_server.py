# dev_server.py — Home hub UI development server
# Serves /api/hub/* routes from fixture files.
# Use for UI testing without any sub-project running.
#
# Run:  cd projects/home-hub && python -m tests.dev_server
# Open: http://localhost:5006
#
# Switch scenarios:
#   GET /api/hub/scenario?name=all_online
#   GET /api/hub/scenario?name=some_offline
#   GET /api/hub/scenario?name=no_data
# Refresh after each.
#
# NOT for production use. Not covered by the test suite.

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = BASE_DIR / "fixtures"
TEMPLATE_DIR = BASE_DIR.parent / "dashboard" / "templates"

app = Flask(__name__, template_folder=str(TEMPLATE_DIR))

SCENARIOS = {
    "all_online": {"services_online": 5, "services_total": 5},
    "some_offline": {"services_online": 3, "services_total": 5},
    "no_data": {"services_online": 0, "services_total": 5, "data_available": False},
}


def load_json(name: str) -> dict:
    with (FIXTURE_DIR / name).open() as fixture_file:
        return json.load(fixture_file)


overview = load_json("hub_overview.json")


def scenario_payload(name: str) -> dict:
    payload = copy.deepcopy(load_json("hub_overview.json"))
    changes = SCENARIOS[name]
    payload.update(changes)
    payload["last_updated"] = datetime.now(timezone.utc).isoformat()

    if name == "some_offline":
        for service in payload["services"][3:]:
            service["online"] = False
            service["data_available"] = False
            service["key_metrics"] = {}
            service["last_updated"] = None
        payload["infrastructure"]["grafana"]["online"] = False
    elif name == "no_data":
        for service in payload["services"]:
            service["online"] = False
            service["data_available"] = False
            service["key_metrics"] = {}
            service["last_updated"] = None
        for item in payload["infrastructure"].values():
            item["online"] = False
    return payload


@app.route("/")
def index():
    return render_template("index.html", username="dev", role="admin", services=overview["services"])


@app.route("/api/hub/overview")
def api_hub_overview():
    return jsonify(overview)


@app.route("/api/hub/status")
def api_hub_status():
    return jsonify({
        "online": True,
        "services_total": overview["services_total"],
        "services_online": overview["services_online"],
        "last_updated": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/hub/scenario")
def api_hub_scenario():
    name = request.args.get("name")
    if name not in SCENARIOS:
        return jsonify({"error": "unknown scenario", "available": sorted(SCENARIOS)}), 400
    overview.clear()
    overview.update(scenario_payload(name))
    return jsonify(overview)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5006)
