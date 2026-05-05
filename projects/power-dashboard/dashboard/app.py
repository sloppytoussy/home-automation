from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from influxdb_client import InfluxDBClient

# Load .env from explicit paths so it works in sandboxed environments
# (avoids os.getcwd() which some sandboxes block)
for _env_candidate in [
    Path(__file__).parent / ".env",
    Path(__file__).parent.parent / ".env",
    Path(__file__).parent.parent.parent.parent / ".env",
]:
    if _env_candidate.exists():
        load_dotenv(_env_candidate, override=False)
        break
else:
    # No .env found — silently continue; env vars may be set externally
    pass

app = Flask(__name__)

APPLIANCES_CONFIG = Path(__file__).parent.parent / "config" / "appliances.yaml"

METER_MODEL = "Landis+Gyr JH145"
TARIFF_CURRENCY = "RWF"
TARIFF_RATE_PER_KWH = 310  # blended mid-tier estimate
INFLUX_REQUIRED_ENV = ("INFLUXDB_URL", "INFLUXDB_TOKEN", "INFLUXDB_ORG", "INFLUXDB_BUCKET")


# ------------------------------------------------------------------
# DB helpers
# ------------------------------------------------------------------

def load_rooms() -> list[dict]:
    with open(APPLIANCES_CONFIG) as f:
        return yaml.safe_load(f).get("rooms", [])


def get_influx():
    return InfluxDBClient(
        url=os.getenv("INFLUXDB_URL"),
        token=os.getenv("INFLUXDB_TOKEN"),
        org=os.getenv("INFLUXDB_ORG"),
    )


def influx_bucket() -> str | None:
    if not all(os.getenv(name) for name in INFLUX_REQUIRED_ENV):
        return None
    return os.getenv("INFLUXDB_BUCKET")


def query(flux: str) -> list[dict]:
    """Raw query — returns {time, field, value} per record."""
    org = os.getenv("INFLUXDB_ORG")
    if not org:
        return []
    with get_influx() as client:
        tables = client.query_api().query(flux, org=org)
        return [
            {"time": rec.get_time(), "field": rec.get_field(), "value": rec.get_value()}
            for table in tables
            for rec in table.records
        ]


def query_pivot(flux: str) -> list[dict]:
    """Pivot-aware query — expands all record values into a flat dict."""
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


def query_safe(flux: str) -> list[dict]:
    try:
        return query(flux)
    except Exception:
        return []


def query_pivot_safe(flux: str) -> list[dict]:
    try:
        return query_pivot(flux)
    except Exception:
        return []


# ------------------------------------------------------------------
# Read helpers
# ------------------------------------------------------------------

def last_meter_reading() -> dict | None:
    bucket = influx_bucket()
    if not bucket:
        return None
    rows = query_pivot_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: -30d)
          |> filter(fn: (r) => r._measurement == "power_meter")
          |> last()
          |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")
    ''')
    if not rows:
        return None
    r = rows[0]
    return {
        "time": r["time"].isoformat() if hasattr(r.get("time"), "isoformat") else None,
        "instant_load_w": r.get("instant_load_w"),
        "lifetime_kwh": r.get("lifetime_kwh"),
        "remaining_kwh": r.get("remaining_kwh"),
        "last_topup_kwh": r.get("topup_kwh"),
        "last_topup_days_ago": None,  # filled below if data available
    }


def consumption_rate_kwh_per_day() -> float | None:
    """Rolling 7-day average daily consumption from lifetime_kwh delta."""
    bucket = influx_bucket()
    if not bucket:
        return None
    rows = query_safe(f'''
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


def today_kwh() -> float | None:
    """kWh consumed since midnight today."""
    bucket = influx_bucket()
    if not bucket:
        return None
    rows = query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: today())
          |> filter(fn: (r) => r._measurement == "power_meter" and r._field == "lifetime_kwh")
          |> sort(columns: ["_time"])
    ''')
    if len(rows) < 2:
        return None
    return round(rows[-1]["value"] - rows[0]["value"], 2)


def peak_load_today_w() -> int | None:
    """Max instant_load_w since midnight."""
    bucket = influx_bucket()
    if not bucket:
        return None
    rows = query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: today())
          |> filter(fn: (r) => r._measurement == "power_meter" and r._field == "instant_load_w")
          |> max()
    ''')
    return round(rows[0]["value"]) if rows else None


def last_topup_info() -> tuple[float | None, int | None]:
    """Returns (last_topup_kwh, last_topup_days_ago)."""
    bucket = influx_bucket()
    if not bucket:
        return None, None
    rows = query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: -365d)
          |> filter(fn: (r) => r._measurement == "power_meter"
              and r._field == "topup_kwh"
              and r._value > 0)
          |> sort(columns: ["_time"], desc: true)
          |> limit(n: 1)
    ''')
    if not rows:
        return None, None
    kwh = rows[0]["value"]
    days_ago = round((datetime.now(timezone.utc) - rows[0]["time"]).total_seconds() / 86400)
    return kwh, days_ago


def daily_kwh_history(days: int = 90) -> list[dict]:
    """Daily kWh consumption from lifetime_kwh deltas."""
    bucket = influx_bucket()
    if not bucket:
        return []
    rows = query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r._measurement == "power_meter" and r._field == "lifetime_kwh")
          |> aggregateWindow(every: 1d, fn: last, createEmpty: false)
          |> difference(nonNegative: true)
          |> filter(fn: (r) => r._value > 0)
          |> sort(columns: ["_time"])
    ''')
    result = []
    for r in rows:
        t = r.get("time")
        if t:
            date_str = t.strftime("%Y-%m-%d") if hasattr(t, "strftime") else str(t)[:10]
            result.append({"date": date_str, "kwh": round(r["value"], 2)})
    return result


def topup_history() -> list[dict]:
    """List of top-up events from InfluxDB."""
    bucket = influx_bucket()
    if not bucket:
        return []
    rows = query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: -365d)
          |> filter(fn: (r) => r._measurement == "power_meter"
              and r._field == "topup_kwh"
              and r._value > 0)
          |> sort(columns: ["_time"], desc: true)
          |> limit(n: 20)
    ''')
    result = []
    for r in rows:
        t = r.get("time")
        if t:
            date_str = t.strftime("%Y-%m-%d") if hasattr(t, "strftime") else str(t)[:10]
            kwh = r["value"]
            result.append({"date": date_str, "kwh": kwh, "cost_rwf": round(kwh * TARIFF_RATE_PER_KWH)})
    return result


def full_appliance_list() -> list[dict]:
    """Join InfluxDB appliance data with YAML config for watts + daily_hours."""
    rooms = load_rooms()
    config_map: dict[tuple, dict] = {}
    for room in rooms:
        for appl in room.get("appliances", []):
            config_map[(room["name"], appl["name"])] = appl

    bucket = influx_bucket()
    if not bucket:
        return []
    rows = query_pivot_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: -90d)
          |> filter(fn: (r) => r._measurement == "power_appliance")
          |> last()
          |> pivot(rowKey:["_time", "room", "appliance"], columnKey:["_field"], valueColumn:"_value")
          |> group()
    ''')

    result = []
    for r in rows:
        rname = r.get("room", "")
        aname = r.get("appliance", "")
        cfg = config_map.get((rname, aname), {})
        result.append({
            "room": rname,
            "appliance": aname,
            "watts": r.get("watts") or cfg.get("rated_watts"),
            "daily_hours": r.get("daily_hours"),
            "est_daily_kwh": round(r.get("est_daily_kwh") or 0, 3),
            "on_now": False,
        })
    return sorted(result, key=lambda x: x["est_daily_kwh"], reverse=True)


def history_load(days: int = 7) -> list[dict]:
    bucket = influx_bucket()
    if not bucket:
        return []
    rows = query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r._measurement == "power_meter" and r._field == "instant_load_w")
          |> sort(columns: ["_time"])
    ''')
    return [{"t": r["time"].isoformat(), "w": round(r["value"])} for r in rows]


def history_remaining(days: int = 30) -> list[dict]:
    bucket = influx_bucket()
    if not bucket:
        return []
    rows = query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r._measurement == "power_meter" and r._field == "remaining_kwh")
          |> sort(columns: ["_time"])
    ''')
    return [{"time": r["time"].isoformat(), "value": r["value"]} for r in rows]


# ------------------------------------------------------------------
# Page routes (kept as-is for entry/appliance forms)
# ------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


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
def appliances_page():
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
        remaining = reading.get("remaining_kwh") or 0
        days_left = round(remaining / rate, 1)

    # Patch in last top-up details
    if reading:
        topup_kwh, topup_days = last_topup_info()
        reading["last_topup_kwh"] = topup_kwh or reading.get("last_topup_kwh")
        reading["last_topup_days_ago"] = topup_days

    t_kwh = today_kwh()
    return jsonify({
        "reading": reading,
        "rate_kwh_per_day": rate,
        "days_left": days_left,
        "today_kwh": t_kwh,
        "avg_kwh": rate,
        "peak_load_today_w": peak_load_today_w(),
        "meter_model": METER_MODEL,
        "tariff_currency": TARIFF_CURRENCY,
        "tariff_rate_per_kwh": TARIFF_RATE_PER_KWH,
    })


@app.route("/api/history/daily")
def api_history_daily():
    days = int(request.args.get("days", 90))
    return jsonify(daily_kwh_history(days))


@app.route("/api/history/load")
def api_history_load():
    days = int(request.args.get("days", 7))
    return jsonify(history_load(days))


@app.route("/api/history/remaining")
def api_history_remaining():
    return jsonify(history_remaining(30))


@app.route("/api/appliances")
def api_appliances():
    return jsonify(full_appliance_list())


@app.route("/api/topups")
def api_topups():
    return jsonify(topup_history())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("POWER_DASHBOARD_PORT", 5001)))
