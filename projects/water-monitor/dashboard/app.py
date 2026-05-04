import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from influxdb_client import InfluxDBClient

load_dotenv()

app = Flask(__name__)
CONFIG_PATH = Path(__file__).parent.parent / "config" / "tanks.yaml"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def load_tanks() -> list[dict]:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)["tanks"]


def get_influx():
    return InfluxDBClient(
        url=os.environ["INFLUXDB_URL"],
        token=os.environ["INFLUXDB_TOKEN"],
        org=os.environ["INFLUXDB_ORG"],
    )


def flux_query(flux: str) -> list:
    with get_influx() as client:
        tables = client.query_api().query(flux, org=os.environ["INFLUXDB_ORG"])
        return [
            {**{rec.get_field(): rec.get_value()}, "time": rec.get_time(), **rec.values}
            for table in tables for rec in table.records
        ]


def latest_reading(tank_id: str) -> dict | None:
    bucket = os.environ["INFLUXDB_BUCKET"]
    rows = flux_query(f'''
        from(bucket: "{bucket}")
          |> range(start: -7d)
          |> filter(fn: (r) => r._measurement == "water_tank" and r.tank_id == "{tank_id}")
          |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")
          |> sort(columns:["_time"], desc: true)
          |> limit(n:1)
    ''')
    return rows[0] if rows else None


def level_history(tank_id: str, days: int = 7) -> list[dict]:
    bucket = os.environ["INFLUXDB_BUCKET"]
    rows = flux_query(f'''
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
    bucket = os.environ["INFLUXDB_BUCKET"]
    rows = flux_query(f'''
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


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@app.route("/")
def index():
    tanks = load_tanks()
    tank_data = []
    for t in tanks:
        reading = latest_reading(t["id"])
        rate = rolling_rate_lph(t["id"])
        days_left = None
        if reading and rate and rate > 0:
            days_left = round(reading.get("volume_liters", 0) / (rate * 24), 1)
        tank_data.append({
            "cfg": t,
            "reading": reading,
            "rate_lph": rate,
            "days_left": days_left,
        })
    return render_template("index.html", tanks=tank_data)


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
        })
    return jsonify(out)


@app.route("/api/history/<tank_id>")
def api_history(tank_id: str):
    days = int(request.args.get("days", 7))
    return jsonify(level_history(tank_id, days))


@app.route("/api/source/<tank_id>", methods=["POST"])
def set_source(tank_id: str):
    """Toggle active source for tank2 between rain and mains."""
    data = request.get_json()
    source = data.get("source", "")
    cfg_text = CONFIG_PATH.read_text()

    tanks = load_tanks()
    tank = next((t for t in tanks if t["id"] == tank_id), None)
    if not tank:
        return jsonify({"error": "tank not found"}), 404
    if source not in tank.get("sources", []):
        return jsonify({"error": f"invalid source '{source}'"}), 400

    # Patch active_source in the YAML file
    import re
    new_text = re.sub(
        r"(active_source:\s*)\S+",
        f"\\g<1>{source}",
        cfg_text,
        count=1,
    )
    CONFIG_PATH.write_text(new_text)
    return jsonify({"tank_id": tank_id, "active_source": source})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("WATER_DASHBOARD_PORT", 5002)))
