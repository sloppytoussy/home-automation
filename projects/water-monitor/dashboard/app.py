from __future__ import annotations

import datetime
import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from influxdb_client import InfluxDBClient

load_dotenv()

app = Flask(__name__)
CONFIG_PATH = Path(__file__).parent.parent / "config" / "tanks.yaml"
INFLUX_REQUIRED_ENV = ("INFLUXDB_URL", "INFLUXDB_TOKEN", "INFLUXDB_ORG", "INFLUXDB_BUCKET")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def load_tanks() -> list[dict]:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)["tanks"]


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


def flux_query(flux: str) -> list:
    org = os.getenv("INFLUXDB_ORG")
    if not org:
        return []
    with get_influx() as client:
        tables = client.query_api().query(flux, org=org)
        return [
            {**{rec.get_field(): rec.get_value()}, "time": rec.get_time(), **rec.values}
            for table in tables for rec in table.records
        ]


def flux_query_safe(flux: str) -> list:
    try:
        return flux_query(flux)
    except Exception:
        return []


def latest_reading(tank_id: str) -> dict | None:
    bucket = influx_bucket()
    if not bucket:
        return None
    rows = flux_query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: -7d)
          |> filter(fn: (r) => r._measurement == "water_tank" and r.tank_id == "{tank_id}")
          |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")
          |> sort(columns:["_time"], desc: true)
          |> limit(n:1)
    ''')
    return rows[0] if rows else None


def level_history(tank_id: str, days: int = 7) -> list[dict]:
    bucket = influx_bucket()
    if not bucket:
        return []
    rows = flux_query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r._measurement == "water_tank"
              and r.tank_id == "{tank_id}"
              and r._field == "volume_liters")
          |> sort(columns:["_time"])
    ''')
    return [{"time": r["time"].isoformat(), "value": r.get("volume_liters", r.get("_value"))} for r in rows]


def rolling_rate_lph(tank_id: str) -> float | None:
    """Litres per hour drain rate over last 24 h (negative delta = consumption)."""
    bucket = influx_bucket()
    if not bucket:
        return None
    rows = flux_query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: -24h)
          |> filter(fn: (r) => r._measurement == "water_tank"
              and r.tank_id == "{tank_id}"
              and r._field == "volume_liters")
          |> sort(columns:["_time"])
    ''')
    if len(rows) < 2:
        return None
    v0 = rows[0].get("volume_liters", rows[0].get("_value", 0))
    v1 = rows[-1].get("volume_liters", rows[-1].get("_value", 0))
    t0 = rows[0]["time"].timestamp()
    t1 = rows[-1]["time"].timestamp()
    delta_h = (t1 - t0) / 3600
    if delta_h <= 0 or v1 >= v0:
        return None
    return round((v0 - v1) / delta_h, 2)


def today_consumption_l(tank_id: str) -> float | None:
    """Volume drop since midnight today."""
    bucket = influx_bucket()
    if not bucket:
        return None
    rows = flux_query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: today())
          |> filter(fn: (r) => r._measurement == "water_tank"
              and r.tank_id == "{tank_id}"
              and r._field == "volume_liters")
          |> sort(columns:["_time"])
    ''')
    if len(rows) < 2:
        return None
    first = rows[0].get("_value", rows[0].get("volume_liters"))
    last = rows[-1].get("_value", rows[-1].get("volume_liters"))
    if first is None or last is None:
        return None
    return max(0, round(first - last, 1))


def avg_daily_consumption_l(tank_id: str) -> float | None:
    """Average daily consumption over last 7 days."""
    bucket = influx_bucket()
    if not bucket:
        return None
    rows = flux_query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: -7d)
          |> filter(fn: (r) => r._measurement == "water_tank"
              and r.tank_id == "{tank_id}"
              and r._field == "volume_liters")
          |> sort(columns:["_time"])
    ''')
    if len(rows) < 2:
        return None
    first = rows[0].get("_value", rows[0].get("volume_liters"))
    last = rows[-1].get("_value", rows[-1].get("volume_liters"))
    if first is None or last is None:
        return None
    drop = max(0, first - last)
    return round(drop / 7, 1)


def pump_status(tank_cfg: dict) -> dict:
    tank_id = tank_cfg["id"]
    bucket = influx_bucket()
    running = False
    runtime_today_min = 0
    if not bucket:
        return {
            "name": tank_cfg.get("pump", {}).get("name", "Dayliff DDA 1000P"),
            "running": running,
            "runtime_today_min": runtime_today_min,
        }

    rows = flux_query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: -5m)
          |> filter(fn: (r) => r._measurement == "pump_state"
              and r.tank_id == "{tank_id}")
          |> last()
    ''')
    if rows:
        running = bool(rows[0].get("_value", 0))

    # Count ON samples today and convert to minutes (assumes ~60s poll interval)
    on_rows = flux_query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: today())
          |> filter(fn: (r) => r._measurement == "pump_state"
              and r.tank_id == "{tank_id}"
              and r._value == 1)
          |> count()
    ''')
    if on_rows:
        runtime_today_min = round(on_rows[0].get("_value", 0) / 60)

    return {
        "name": tank_cfg.get("pump", {}).get("name", "Dayliff DDA 1000P"),
        "running": running,
        "runtime_today_min": runtime_today_min,
    }


def sensor_status(tank_id: str) -> dict:
    bucket = influx_bucket()
    if not bucket:
        return {"battery_pct": None, "last_seen_min": None}
    rows = flux_query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: -24h)
          |> filter(fn: (r) => r._measurement == "sensor_battery"
              and r.tank_id == "{tank_id}")
          |> last()
    ''')
    if not rows:
        return {"battery_pct": None, "last_seen_min": None}
    rec = rows[0]
    battery_pct = rec.get("_value")
    last_seen_ts = rec.get("time")
    last_seen_min = None
    if last_seen_ts and hasattr(last_seen_ts, "timestamp"):
        now = datetime.datetime.now(datetime.timezone.utc)
        last_seen_min = max(0, round((now.timestamp() - last_seen_ts.timestamp()) / 60))
    return {"battery_pct": battery_pct, "last_seen_min": last_seen_min}


def daily_consumption_history(days: int = 90) -> list[dict]:
    """Combined daily consumption (L/day) across all tanks for the heatmap."""
    bucket = influx_bucket()
    if not bucket:
        return []
    rows = flux_query_safe(f'''
        from(bucket: "{bucket}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r._measurement == "water_tank"
              and r._field == "volume_liters")
          |> aggregateWindow(every: 1d, fn: last, createEmpty: false)
          |> difference(nonNegative: false)
          |> map(fn: (r) => ({{ r with _value: -r._value }}))
          |> filter(fn: (r) => r._value > 0)
          |> group(columns: ["_time"])
          |> sum()
          |> sort(columns: ["_time"])
    ''')
    result = []
    for r in rows:
        t = r.get("time") or r.get("_time")
        if t:
            date_str = t.strftime("%Y-%m-%d") if hasattr(t, "strftime") else str(t)[:10]
            result.append({"date": date_str, "liters": round(r.get("_value", 0))})
    return result


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/tanks")
def api_tanks():
    tanks = load_tanks()
    out = []
    for t in tanks:
        reading = latest_reading(t["id"])
        rate = rolling_rate_lph(t["id"])
        days_left = None
        if reading and rate and rate > 0:
            days_left = round(reading.get("volume_liters", 0) / (rate * 24), 1)
        out.append({
            "id": t["id"],
            "name": t["name"],
            "capacity_liters": t["capacity_liters"],
            "sources": t["sources"],
            "active_source": t.get("active_source", t["sources"][0]),
            "low_threshold_pct": t.get("low_threshold_pct", 20),
            "reading": reading,
            "rate_lph": rate,
            "days_left": days_left,
            "today_consumption_l": today_consumption_l(t["id"]),
            "avg_consumption_l": avg_daily_consumption_l(t["id"]),
            "pump": pump_status(t),
            "sensor": sensor_status(t["id"]),
        })
    return jsonify(out)


@app.route("/api/history/<tank_id>")
def api_history(tank_id: str):
    days = int(request.args.get("days", 7))
    return jsonify(level_history(tank_id, days))


@app.route("/api/consumption")
def api_consumption():
    days = int(request.args.get("days", 90))
    return jsonify(daily_consumption_history(days))


# This endpoint is intentionally unauthenticated: the dashboard is local-only
# (home network). If exposed publicly, add a shared-secret or session token.
@app.route("/api/source/<tank_id>", methods=["POST"])
def set_source(tank_id: str):
    """Set active_source for a specific tank. Rewrites tanks.yaml in-place,
    preserving all comments, by scoping the replacement to the correct tank block."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    source = data.get("source", "")

    tanks = load_tanks()
    tank = next((t for t in tanks if t["id"] == tank_id), None)
    if not tank:
        return jsonify({"error": "tank not found"}), 404
    if source not in tank.get("sources", []):
        return jsonify({"error": f"invalid source '{source}'"}), 400

    cfg_text = CONFIG_PATH.read_text()
    lines = cfg_text.splitlines(keepends=True)
    in_target = False
    replaced = False
    for i, line in enumerate(lines):
        if re.match(rf"\s+-\s+id:\s+{re.escape(tank_id)}\s*$", line):
            in_target = True
        elif in_target and re.match(r"\s+-\s+id:\s+\S+", line):
            break  # entered a different tank block
        if in_target and re.match(r"\s+active_source:\s+\S+", line):
            lines[i] = re.sub(r"(active_source:\s+)\S+", rf"\g<1>{source}", line)
            replaced = True
            break

    if not replaced:
        return jsonify({"error": "active_source field not present for this tank"}), 422

    CONFIG_PATH.write_text("".join(lines))
    return jsonify({"tank_id": tank_id, "active_source": source})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("WATER_DASHBOARD_PORT", 5002)))
