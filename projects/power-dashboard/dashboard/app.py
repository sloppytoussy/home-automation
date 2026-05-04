import os
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for
from influxdb_client import InfluxDBClient

load_dotenv()

app = Flask(__name__)

APPLIANCES_CONFIG = Path(__file__).parent.parent / "config" / "appliances.yaml"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def load_rooms() -> list[dict]:
    with open(APPLIANCES_CONFIG) as f:
        return yaml.safe_load(f).get("rooms", [])


def get_influx():
    return InfluxDBClient(
        url=os.environ["INFLUXDB_URL"],
        token=os.environ["INFLUXDB_TOKEN"],
        org=os.environ["INFLUXDB_ORG"],
    )


def query(flux: str) -> list[dict]:
    with get_influx() as client:
        tables = client.query_api().query(flux, org=os.environ["INFLUXDB_ORG"])
        return [
            {"time": rec.get_time(), "field": rec.get_field(), "value": rec.get_value()}
            for table in tables
            for rec in table.records
        ]


def last_meter_reading() -> dict | None:
    bucket = os.environ["INFLUXDB_BUCKET"]
    rows = query(f'''
        from(bucket: "{bucket}")
          |> range(start: -30d)
          |> filter(fn: (r) => r._measurement == "power_meter")
          |> last()
          |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")
    ''')
    return rows[0] if rows else None


def consumption_rate_kwh_per_day() -> float | None:
    """Rolling 7-day average daily consumption from lifetime_kwh delta."""
    bucket = os.environ["INFLUXDB_BUCKET"]
    rows = query(f'''
        from(bucket: "{bucket}")
          |> range(start: -7d)
          |> filter(fn: (r) => r._measurement == "power_meter" and r._field == "lifetime_kwh")
          |> sort(columns: ["_time"])
    ''')
    if len(rows) < 2:
        return None
    delta_kwh = rows[-1]["value"] - rows[0]["value"]
    delta_days = (rows[-1]["time"] - rows[0]["time"]).total_seconds() / 86400
    return round(delta_kwh / delta_days, 3) if delta_days > 0 else None


def history_remaining(days: int = 30) -> list[dict]:
    bucket = os.environ["INFLUXDB_BUCKET"]
    rows = query(f'''
        from(bucket: "{bucket}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r._measurement == "power_meter" and r._field == "remaining_kwh")
          |> sort(columns: ["_time"])
    ''')
    return [{"time": r["time"].isoformat(), "value": r["value"]} for r in rows]


def history_load(days: int = 7) -> list[dict]:
    bucket = os.environ["INFLUXDB_BUCKET"]
    rows = query(f'''
        from(bucket: "{bucket}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r._measurement == "power_meter" and r._field == "instant_load_w")
          |> sort(columns: ["_time"])
    ''')
    return [{"time": r["time"].isoformat(), "value": r["value"]} for r in rows]


def appliance_summary() -> list[dict]:
    bucket = os.environ["INFLUXDB_BUCKET"]
    rows = query(f'''
        from(bucket: "{bucket}")
          |> range(start: -30d)
          |> filter(fn: (r) => r._measurement == "power_appliance" and r._field == "est_daily_kwh")
          |> last()
          |> group(columns: ["room", "appliance"])
    ''')
    out = []
    for r in rows:
        out.append({
            "room": r.get("room", ""),
            "appliance": r.get("appliance", ""),
            "est_daily_kwh": r["value"],
        })
    return sorted(out, key=lambda x: x["est_daily_kwh"], reverse=True)


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@app.route("/")
def index():
    reading = last_meter_reading()
    rate = consumption_rate_kwh_per_day()
    days_left = None
    if reading and rate and rate > 0:
        remaining = reading.get("remaining_kwh") or reading.get("value", 0)
        days_left = round(remaining / rate, 1)
    return render_template(
        "index.html",
        reading=reading,
        rate=rate,
        days_left=days_left,
        now=datetime.now(timezone.utc),
    )


@app.route("/entry", methods=["GET", "POST"])
def entry():
    error = None
    success = False
    if request.method == "POST":
        try:
            from collector.writer import PowerWriter
            writer = PowerWriter()
            topup = request.form.get("topup_kwh")
            writer.write_meter_reading(
                instant_load_w=float(request.form["instant_load_w"]),
                lifetime_kwh=float(request.form["lifetime_kwh"]),
                remaining_kwh=float(request.form["remaining_kwh"]),
                topup_kwh=float(topup) if topup else None,
                notes=request.form.get("notes", ""),
            )
            writer.close()
            success = True
        except Exception as e:
            error = str(e)
    return render_template("entry.html", error=error, success=success)


@app.route("/appliances", methods=["GET", "POST"])
def appliances():
    rooms = load_rooms()
    error = None
    success = False
    if request.method == "POST":
        try:
            from collector.writer import PowerWriter
            writer = PowerWriter()
            daily_h = request.form.get("daily_hours")
            writer.write_appliance_reading(
                room=request.form["room"],
                appliance=request.form["appliance"],
                watts=float(request.form["watts"]),
                daily_hours=float(daily_h) if daily_h else None,
            )
            writer.close()
            success = True
        except Exception as e:
            error = str(e)
    return render_template("appliances.html", rooms=rooms, error=error, success=success)


# ------------------------------------------------------------------
# JSON API
# ------------------------------------------------------------------

@app.route("/api/summary")
def api_summary():
    reading = last_meter_reading()
    rate = consumption_rate_kwh_per_day()
    days_left = None
    if reading and rate and rate > 0:
        remaining = reading.get("remaining_kwh", 0)
        days_left = round(remaining / rate, 1)
    return jsonify({"reading": reading, "rate_kwh_per_day": rate, "days_left": days_left})


@app.route("/api/history/remaining")
def api_history_remaining():
    return jsonify(history_remaining(30))


@app.route("/api/history/load")
def api_history_load():
    return jsonify(history_load(7))


@app.route("/api/appliances")
def api_appliances():
    return jsonify(appliance_summary())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("POWER_DASHBOARD_PORT", 5001)))
