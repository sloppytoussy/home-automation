from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import yaml
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from influxdb_client import InfluxDBClient
from yaml import YAMLError

from collector import writer
from shared.auth.blueprint import auth_bp
from shared.auth.decorators import require_admin, require_auth

for _env_candidate in [
    Path(__file__).parent / ".env",
    Path(__file__).parent.parent / ".env",
    Path(__file__).parent.parent.parent.parent / ".env",
]:
    if _env_candidate.exists():
        load_dotenv(_env_candidate, override=False)
        break

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-key-replace-in-production")
app.register_blueprint(auth_bp)
CONFIG_PATH = Path(__file__).parent.parent / "config" / "lighting.yaml"
INFLUX_REQUIRED_ENV = ("INFLUXDB_URL", "INFLUXDB_TOKEN", "INFLUXDB_ORG", "INFLUXDB_BUCKET")
ONLINE_THRESHOLD_MINUTES = 5
MAX_HISTORY_HOURS = 168


def load_config() -> dict[str, Any]:
    try:
        with CONFIG_PATH.open() as config_file:
            return yaml.safe_load(config_file) or {}
    except (FileNotFoundError, YAMLError) as exc:
        app.logger.warning("Unable to load lighting config: %s", exc)
        return {}


def get_influx() -> InfluxDBClient:
    return InfluxDBClient(
        url=os.getenv("INFLUXDB_URL"),
        token=os.getenv("INFLUXDB_TOKEN"),
        org=os.getenv("INFLUXDB_ORG"),
    )


def influx_bucket() -> str | None:
    if not all(os.getenv(name) for name in INFLUX_REQUIRED_ENV):
        return None
    return os.getenv("INFLUXDB_BUCKET")


def query_pivot(flux: str) -> list[dict[str, Any]]:
    org = os.getenv("INFLUXDB_ORG")
    if not org:
        return []
    with get_influx() as client:
        tables = client.query_api().query(flux, org=org)
        return [{"time": rec.get_time(), **rec.values} for table in tables for rec in table.records]


def iso_time(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return None
    return None


def minutes_since(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 60, 1)


def devices_by_id() -> dict[str, dict[str, Any]]:
    return {device["id"]: device for device in load_config().get("devices", [])}


def room_names() -> dict[str, str]:
    return {room["id"]: room["name"] for room in load_config().get("rooms", [])}


def latest_device_rows() -> list[dict[str, Any]]:
    bucket = influx_bucket()
    if not bucket:
        return []
    return query_pivot(f'''
        from(bucket: "{bucket}")
          |> range(start: -30d)
          |> filter(fn: (r) => r._measurement == "lighting_state")
          |> group(columns: ["device_id", "_field"])
          |> last()
          |> pivot(rowKey: ["device_id"], columnKey: ["_field"], valueColumn: "_value")
    ''')


def history_rows(device_id: str, hours: int) -> list[dict[str, Any]]:
    bucket = influx_bucket()
    if not bucket:
        return []
    return query_pivot(f'''
        from(bucket: "{bucket}")
          |> range(start: -{hours}h)
          |> filter(fn: (r) => r._measurement == "lighting_state" and r.device_id == "{device_id}")
          |> filter(fn: (r) => contains(value: r._field, set: ["is_on", "power_w", "brightness_pct"]))
          |> aggregateWindow(every: 5m, fn: last, createEmpty: false)
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"])
    ''')


def normalize_device(row: dict[str, Any]) -> dict[str, Any]:
    device_id = row.get("device_id")
    cfg = devices_by_id().get(device_id, {})
    last_seen = row.get("time") or row.get("_time")
    age = minutes_since(last_seen)
    return {
        "device_id": device_id,
        "name": cfg.get("name", device_id),
        "room": row.get("room") or cfg.get("room"),
        "device_type": row.get("device_type") or cfg.get("type"),
        "generation": row.get("generation") or cfg.get("generation"),
        "is_on": row.get("is_on"),
        "brightness_pct": row.get("brightness_pct"),
        "power_w": row.get("power_w"),
        "last_seen": iso_time(last_seen),
        "online": age is not None and age < ONLINE_THRESHOLD_MINUTES,
    }


def empty_overview() -> dict[str, Any]:
    return {
        "devices_total": None,
        "devices_on": None,
        "rooms_total": None,
        "rooms_with_lights_on": None,
        "total_power_w": None,
        "data_available": False,
    }


def overview_from_devices(devices: list[dict[str, Any]]) -> dict[str, Any]:
    if not devices:
        return empty_overview()
    rooms = {device["room"] for device in devices if device.get("room")}
    rooms_on = {device["room"] for device in devices if device.get("room") and device.get("is_on")}
    return {
        "devices_total": len(devices),
        "devices_on": sum(1 for device in devices if device.get("is_on")),
        "rooms_total": len(rooms),
        "rooms_with_lights_on": len(rooms_on),
        "total_power_w": round(sum(float(device.get("power_w") or 0) for device in devices), 1),
        "data_available": True,
    }


def rooms_from_devices(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names = room_names()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for device in devices:
        if device.get("room"):
            grouped.setdefault(device["room"], []).append(device)
    return [
        {
            "room_id": room_id,
            "name": names.get(room_id, room_id.replace("_", " ").title()),
            "devices_total": len(room_devices),
            "devices_on": sum(1 for device in room_devices if device.get("is_on")),
            "total_power_w": round(sum(float(device.get("power_w") or 0) for device in room_devices), 1),
        }
        for room_id, room_devices in sorted(grouped.items())
    ]


def parse_history_hours() -> int:
    raw_hours = request.args.get("hours", "24")
    try:
        hours = int(raw_hours)
    except (TypeError, ValueError) as exc:
        raise ValueError("hours must be an integer") from exc
    if hours <= 0 or hours > MAX_HISTORY_HOURS:
        raise ValueError("hours must be between 1 and 168")
    return hours


def mqtt_client() -> mqtt.Client:
    client = mqtt.Client(client_id="lighting-dashboard-api")
    if os.getenv("MQTT_USERNAME"):
        client.username_pw_set(os.getenv("MQTT_USERNAME"), os.getenv("MQTT_PASSWORD", ""))
    cfg = load_config().get("mqtt", {})
    client.connect(os.getenv("MQTT_BROKER_HOST", cfg.get("broker_host", "localhost")), int(os.getenv("MQTT_BROKER_PORT", cfg.get("broker_port", 1883))))
    return client


def publish_command(device: dict[str, Any], body: dict[str, Any]) -> None:
    client = mqtt_client()
    try:
        if device["generation"] == "gen1":
            payload = "on" if body.get("on", False) else "off"
            topic = f"shellies/{device['shelly_id']}/relay/0/command"
        else:
            method = "Light.Set" if "brightness" in body or device.get("dimmable") else "Switch.Set"
            params = {"id": 0}
            if "on" in body:
                params["on"] = bool(body["on"])
            if "brightness" in body:
                params["brightness"] = int(body["brightness"])
            topic = f"{device['shelly_id']}/rpc"
            payload = json.dumps({"id": 1, "src": "lighting-dashboard", "method": method, "params": params})
        client.publish(topic, payload)
    finally:
        client.disconnect()


def bad_request(exc: ValueError):
    app.logger.warning("Bad request: %s", exc)
    return jsonify({"error": "invalid input"}), 400


def service_error(exc: Exception):
    app.logger.error("Service error: %s", exc, exc_info=True)
    return jsonify({"error": "service unavailable"}), 503


@app.route("/")
@require_auth
def index():
    return render_template("index.html")


@app.route("/api/lighting/overview")
@require_auth
def api_lighting_overview():
    try:
        return jsonify(overview_from_devices([normalize_device(row) for row in latest_device_rows()]))
    except ValueError as exc:
        return bad_request(exc)
    except Exception as exc:
        return service_error(exc)


@app.route("/api/lighting/devices")
@require_auth
def api_lighting_devices():
    try:
        return jsonify([normalize_device(row) for row in latest_device_rows()])
    except ValueError as exc:
        return bad_request(exc)
    except Exception as exc:
        return service_error(exc)


@app.route("/api/lighting/devices/<device_id>")
@require_auth
def api_lighting_device(device_id: str):
    try:
        if device_id not in devices_by_id():
            return jsonify({"error": "device not found"}), 404
        for row in latest_device_rows():
            if row.get("device_id") == device_id:
                return jsonify(normalize_device(row))
        return jsonify({"error": "device not found"}), 404
    except ValueError as exc:
        return bad_request(exc)
    except Exception as exc:
        return service_error(exc)


@app.route("/api/lighting/devices/<device_id>/set", methods=["POST"])
@require_auth
@require_admin
def api_lighting_device_set(device_id: str):
    try:
        device = devices_by_id().get(device_id)
        if not device:
            return jsonify({"error": "device not found"}), 404
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError("body must be JSON")
        if "on" not in body and "brightness" not in body:
            raise ValueError("body must include on or brightness")
        if "on" in body and not isinstance(body["on"], bool):
            raise ValueError("on must be boolean")
        if "brightness" in body:
            brightness = int(body["brightness"])
            if brightness < 0 or brightness > 100:
                raise ValueError("brightness must be between 0 and 100")
            body["brightness"] = brightness
        publish_command(device, body)
        event_type = "dim" if "brightness" in body else ("on" if body.get("on") else "off")
        writer.write_event(None, device_id, device["room"], event_type, "api", body.get("brightness"))
        return jsonify({"ok": True})
    except ValueError as exc:
        return bad_request(exc)
    except Exception as exc:
        return service_error(exc)


@app.route("/api/lighting/rooms")
@require_auth
def api_lighting_rooms():
    try:
        return jsonify(rooms_from_devices([normalize_device(row) for row in latest_device_rows()]))
    except ValueError as exc:
        return bad_request(exc)
    except Exception as exc:
        return service_error(exc)


@app.route("/api/lighting/history")
@require_auth
def api_lighting_history():
    try:
        device_id = request.args.get("device_id")
        if device_id not in devices_by_id():
            return jsonify({"error": "device not found"}), 404
        hours = parse_history_hours()
        return jsonify([
            {
                "time": iso_time(row.get("time") or row.get("_time")),
                "is_on": row.get("is_on"),
                "power_w": row.get("power_w"),
                "brightness_pct": row.get("brightness_pct"),
            }
            for row in history_rows(device_id, hours)
        ])
    except ValueError as exc:
        return bad_request(exc)
    except Exception as exc:
        return service_error(exc)


@app.route("/api/lighting/status")
@require_auth
def api_lighting_status():
    try:
        rows = latest_device_rows()
        devices = [normalize_device(row) for row in rows]
        last_seen = min((minutes_since(row.get("time") or row.get("_time")) for row in rows), default=None)
        return jsonify({
            "mqtt_connected": bool(os.getenv("MQTT_BROKER_HOST", load_config().get("mqtt", {}).get("broker_host"))),
            "influxdb_ok": influx_bucket() is not None,
            "device_count": len(devices_by_id()),
            "data_available": bool(rows),
            "last_event_minutes_ago": last_seen,
        })
    except ValueError as exc:
        return bad_request(exc)
    except Exception as exc:
        return service_error(exc)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("LIGHTING_DASHBOARD_PORT", 5005)))
