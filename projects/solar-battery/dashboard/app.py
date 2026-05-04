import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template
from influxdb_client import InfluxDBClient

load_dotenv()

app = Flask(__name__)
CONFIG_PATH = Path(__file__).parent.parent / "config" / "inverter.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_influx():
    return InfluxDBClient(
        url=os.environ["INFLUXDB_URL"],
        token=os.environ["INFLUXDB_TOKEN"],
        org=os.environ["INFLUXDB_ORG"],
    )


def flux(query: str) -> list:
    with get_influx() as client:
        tables = client.query_api().query(query, org=os.environ["INFLUXDB_ORG"])
        return [
            {**{r.get_field(): r.get_value()}, "time": r.get_time(), **r.values}
            for t in tables for r in t.records
        ]


def latest() -> dict:
    bucket = os.environ["INFLUXDB_BUCKET"]
    rows = flux(f'''
        from(bucket: "{bucket}")
          |> range(start: -1h)
          |> filter(fn: (r) => r._measurement == "solar")
          |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")
          |> sort(columns:["_time"], desc:true)
          |> limit(n:1)
    ''')
    return rows[0] if rows else {}


def history(field: str, hours: int = 24) -> list[dict]:
    bucket = os.environ["INFLUXDB_BUCKET"]
    rows = flux(f'''
        from(bucket: "{bucket}")
          |> range(start: -{hours}h)
          |> filter(fn: (r) => r._measurement == "solar" and r._field == "{field}")
          |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
          |> sort(columns:["_time"])
    ''')
    return [{"time": r["time"].isoformat(), "value": r.get(field, r.get("_value"))} for r in rows]


def daily_yields(days: int = 14) -> list[dict]:
    bucket = os.environ["INFLUXDB_BUCKET"]
    rows = flux(f'''
        from(bucket: "{bucket}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r._measurement == "solar" and r._field == "daily_yield_kwh")
          |> aggregateWindow(every: 1d, fn: max, createEmpty: false)
          |> sort(columns:["_time"])
    ''')
    return [{"time": r["time"].isoformat(), "value": r.get("daily_yield_kwh", r.get("_value"))} for r in rows]


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@app.route("/")
def index():
    cfg = load_config()
    return render_template("index.html", system=cfg.get("system", {}), battery=cfg.get("battery", {}))


@app.route("/api/live")
def api_live():
    return jsonify(latest())


@app.route("/api/history/<field>")
def api_history(field: str):
    safe_fields = {
        "pv_power_w", "battery_soc_pct", "battery_power_w",
        "load_power_w", "grid_power_w", "battery_voltage_v", "inverter_temp_c",
    }
    if field not in safe_fields:
        return jsonify({"error": "unknown field"}), 400
    hours = int(flask_request_args_get("hours", 24))
    return jsonify(history(field, hours))


@app.route("/api/yield")
def api_yield():
    return jsonify(daily_yields(14))


def flask_request_args_get(key, default):
    from flask import request as _req
    return _req.args.get(key, default)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("SOLAR_DASHBOARD_PORT", 5003)))
