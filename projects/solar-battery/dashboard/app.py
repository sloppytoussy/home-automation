from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import yaml
from yaml import YAMLError
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from influxdb_client import InfluxDBClient

for _env_candidate in [
    Path(__file__).parent / ".env",
    Path(__file__).parent.parent / ".env",
    Path(__file__).parent.parent.parent.parent / ".env",
]:
    if _env_candidate.exists():
        load_dotenv(_env_candidate, override=False)
        break

app = Flask(__name__)
CONFIG_PATH = Path(__file__).parent.parent / "config" / "inverter.yaml"
INFLUX_REQUIRED_ENV = ("INFLUXDB_URL", "INFLUXDB_TOKEN", "INFLUXDB_ORG", "INFLUXDB_BUCKET")
LEGACY_HISTORY_MAX_HOURS = 168
INVERTER_ONLINE_THRESHOLD_W = 5.0

MPPT_STATE_LABELS = {
    0: "Off",
    2: "Fault",
    3: "Bulk",
    4: "Absorption",
    5: "Float",
}

SOLAR_FIELDS = (
    "pv_power_w",
    "pv_yield_today_kwh",
    "battery_soc_pct",
    "battery_power_w",
    "battery_voltage_v",
    "battery_current_a",
    "grid_power_w",
    "ac_load_w",
    "inverter_output_w",
    "mppt_state",
)


def load_config() -> dict:
    try:
        with CONFIG_PATH.open() as f:
            return yaml.safe_load(f) or {}
    except (FileNotFoundError, YAMLError) as exc:
        app.logger.warning("Unable to load config: %s", exc)
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


def query_pivot(flux: str) -> list[dict]:
    org = os.getenv("INFLUXDB_ORG")
    if not org:
        return []
    with get_influx() as client:
        tables = client.query_api().query(flux, org=org)
        return [
            {"time": rec.get_time(), **rec.values}
            for table in tables
            for rec in table.records
        ]


def mppt_state_label(state: object) -> str:
    try:
        return MPPT_STATE_LABELS.get(int(state), "Unknown")
    except (TypeError, ValueError):
        return "Unknown"


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


def date_value(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def empty_summary() -> dict:
    return {
        "time": None,
        "device": None,
        "portal_id": None,
        "source": None,
        "data_available": False,
        "mppt_state_label": "Unknown",
        "last_updated": None,
        **{field: None for field in SOLAR_FIELDS},
    }


def normalize_summary(row: dict | None) -> dict:
    if not row:
        return empty_summary()
    result = empty_summary()
    result.update({
        "time": iso_time(row.get("time") or row.get("_time")),
        "device": row.get("device"),
        "portal_id": row.get("portal_id"),
        "source": row.get("source"),
        "data_available": True,
        "last_updated": iso_time(row.get("time") or row.get("_time")),
    })
    for field in SOLAR_FIELDS:
        result[field] = row.get(field)
    result["mppt_state_label"] = mppt_state_label(result.get("mppt_state"))
    return result


def latest_solar_reading() -> dict | None:
    bucket = influx_bucket()
    if not bucket:
        return None
    rows = query_pivot(f'''
        from(bucket: "{bucket}")
          |> range(start: -30d)
          |> filter(fn: (r) => r._measurement == "solar_readings")
          |> sort(columns: ["_time"], desc: true)
          |> limit(n: 1)
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
    ''')
    return rows[0] if rows else None


def battery_history() -> list[dict]:
    bucket = influx_bucket()
    if not bucket:
        return []
    rows = query_pivot(f'''
        from(bucket: "{bucket}")
          |> range(start: -24h)
          |> filter(fn: (r) => r._measurement == "solar_readings")
          |> filter(fn: (r) => contains(
              value: r._field,
              set: ["battery_soc_pct", "battery_power_w", "battery_voltage_v", "battery_current_a"]
          ))
          |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"])
    ''')
    return [
        {
            "time": iso_time(row.get("time") or row.get("_time")),
            "soc_pct": row.get("battery_soc_pct"),
            "power_w": row.get("battery_power_w"),
            "voltage_v": row.get("battery_voltage_v"),
            "current_a": row.get("battery_current_a"),
        }
        for row in rows
    ]


def pv_yield_history() -> list[dict]:
    bucket = influx_bucket()
    if not bucket:
        return []
    rows = query_pivot(f'''
        from(bucket: "{bucket}")
          |> range(start: -7d)
          |> filter(fn: (r) => r._measurement == "solar_readings" and r._field == "pv_yield_today_kwh")
          |> aggregateWindow(every: 1d, fn: max, createEmpty: false)
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"])
    ''')
    return [
        {
            "date": date_value(row.get("time") or row.get("_time")),
            "yield_kwh": row.get("pv_yield_today_kwh"),
        }
        for row in rows
    ]


def parse_history_days() -> int:
    raw_days = request.args.get("days", "30")
    try:
        days = int(raw_days)
    except (TypeError, ValueError) as exc:
        raise ValueError("days must be an integer") from exc
    if days < 1 or days > 365:
        raise ValueError("days must be between 1 and 365")
    return days


def daily_energy_history(days: int) -> list[dict]:
    bucket = influx_bucket()
    if not bucket:
        return []
    rows = query_pivot(f'''
        from(bucket: "{bucket}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r._measurement == "energy_totals")
          |> filter(fn: (r) => contains(
              value: r._field,
              set: [
                  "pv_yield_kwh",
                  "grid_import_kwh",
                  "grid_export_kwh",
                  "avg_battery_soc_pct",
                  "peak_pv_power_w",
              ]
          ))
          |> aggregateWindow(every: 1d, fn: last, createEmpty: false)
          |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"])
    ''')
    return [
        {
            "date": date_value(row.get("time") or row.get("_time")),
            "pv_yield_kwh": row.get("pv_yield_kwh"),
            "grid_import_kwh": row.get("grid_import_kwh"),
            "grid_export_kwh": row.get("grid_export_kwh"),
            "avg_battery_soc_pct": row.get("avg_battery_soc_pct"),
            "peak_pv_power_w": row.get("peak_pv_power_w"),
        }
        for row in rows
    ]


def minutes_since(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(parsed)
    else:
        dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 60, 1)


def solar_status(row: dict | None) -> dict:
    if not row:
        return {
            "data_available": False,
            "last_seen_minutes_ago": None,
            "cerbo_online": False,
            "mppt_online": False,
            "inverter_online": False,
        }

    last_seen = minutes_since(row.get("time") or row.get("_time"))
    cerbo_online = last_seen is not None and last_seen < 5
    state = row.get("mppt_state")
    inverter_output = row.get("inverter_output_w")
    return {
        "data_available": True,
        "last_seen_minutes_ago": last_seen,
        "cerbo_online": cerbo_online,
        "mppt_online": cerbo_online and state not in (None, 0),
        "inverter_online": (
            cerbo_online
            and inverter_output is not None
            and abs(float(inverter_output)) >= INVERTER_ONLINE_THRESHOLD_W
        ),
    }


def solar_bad_request(exc: ValueError):
    app.logger.warning("Bad request: %s", exc)
    return jsonify({"error": "invalid input"}), 400


def influx_error_response(exc: Exception):
    app.logger.error("InfluxDB error: %s", exc, exc_info=True)
    return jsonify({"error": "InfluxDB unavailable"}), 503


@app.route("/")
def index():
    cfg = load_config()
    return render_template("index.html", system=cfg.get("system", {}), battery=cfg.get("battery", {}))


@app.route("/api/live")
def api_live():
    try:
        return jsonify(normalize_summary(latest_solar_reading()))
    except Exception as exc:
        return influx_error_response(exc)


@app.route("/api/history/<field>")
def api_history(field: str):
    field_aliases = {
        "pv_power": "pv_power_w",
        "battery_voltage": "battery_voltage_v",
        "battery_soc": "battery_soc_pct",
        "load_power": "ac_load_w",
    }
    safe_fields = {
        "pv_power_w",
        "battery_soc_pct",
        "battery_power_w",
        "ac_load_w",
        "grid_power_w",
        "battery_voltage_v",
        "inverter_output_w",
    }
    field = field_aliases.get(field, field)
    if field not in safe_fields:
        return jsonify({"error": "unknown field"}), 400
    try:
        hours = int(request.args.get("hours", 24))
        if hours < 1 or hours > LEGACY_HISTORY_MAX_HOURS:
            raise ValueError("hours must be between 1 and 168")
        bucket = influx_bucket()
        if not bucket:
            return jsonify([])
        rows = query_pivot(f'''
            from(bucket: "{bucket}")
              |> range(start: -{hours}h)
              |> filter(fn: (r) => r._measurement == "solar_readings" and r._field == "{field}")
              |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
              |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
              |> sort(columns: ["_time"])
        ''')
        return jsonify([
            {"time": iso_time(row.get("time") or row.get("_time")), "value": row.get(field)}
            for row in rows
        ])
    except ValueError as exc:
        return solar_bad_request(exc)
    except Exception as exc:
        return influx_error_response(exc)


@app.route("/api/yield")
def api_yield():
    try:
        return jsonify([
            {"time": row["date"], "value": row["yield_kwh"]}
            for row in pv_yield_history()
        ])
    except Exception as exc:
        return influx_error_response(exc)


@app.route("/api/solar/summary")
def api_solar_summary():
    try:
        return jsonify(normalize_summary(latest_solar_reading()))
    except ValueError as exc:
        return solar_bad_request(exc)
    except Exception as exc:
        return influx_error_response(exc)


@app.route("/api/solar/battery")
def api_solar_battery():
    try:
        return jsonify(battery_history())
    except ValueError as exc:
        return solar_bad_request(exc)
    except Exception as exc:
        return influx_error_response(exc)


@app.route("/api/solar/pv")
def api_solar_pv():
    try:
        return jsonify(pv_yield_history())
    except ValueError as exc:
        return solar_bad_request(exc)
    except Exception as exc:
        return influx_error_response(exc)


@app.route("/api/solar/history")
def api_solar_history():
    try:
        return jsonify(daily_energy_history(parse_history_days()))
    except ValueError as exc:
        return solar_bad_request(exc)
    except Exception as exc:
        return influx_error_response(exc)


@app.route("/api/solar/status")
def api_solar_status():
    try:
        return jsonify(solar_status(latest_solar_reading()))
    except ValueError as exc:
        return solar_bad_request(exc)
    except Exception as exc:
        return influx_error_response(exc)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SOLAR_DASHBOARD_PORT", 5003)))
