# Task: solar-battery-phase1-dashboard

**Branch:** `feature/solar-battery-phase1-dashboard`
**Scope:** `projects/solar-battery/` only — no power-dashboard changes this session

## Context

Cerbo GX hardware is not yet purchased. This session builds the solar
dashboard UI, Flask API routes, and InfluxDB query layer against the
schema that the Victron collector will populate in Phase 2.

The collector (victron_collector.py) already has a stub with the full
Victron MQTT topic map. Do not replace or modify it this session.

Battery type: third-party LifePO4 2×12V 200Ah with integrated BMS.
The Cerbo GX will only expose SOC, voltage, current, and power from the
BMS — no cell-level data. Design the dashboard accordingly.

Topology: hybrid (grid-tied with battery backup and solar).

## Allowed files

```
projects/solar-battery/dashboard/app.py                         MODIFY
projects/solar-battery/dashboard/templates/index.html           MODIFY or CREATE
projects/solar-battery/config/solar_collector.yaml              CREATE
projects/solar-battery/config/schema.md                         CREATE
projects/solar-battery/tests/test_app.py                        CREATE or MODIFY
projects/solar-battery/tests/dev_server.py                      CREATE
projects/solar-battery/tests/fixtures/solar_readings.csv        ALREADY EXISTS
projects/solar-battery/tests/fixtures/energy_totals.csv         ALREADY EXISTS
projects/solar-battery/tests/fixtures/solar_summary_latest.json ALREADY EXISTS
projects/solar-battery/tests/fixtures/battery_history.json      ALREADY EXISTS
AGENTS.md                                                       MODIFY (session close)
```

Do not touch any file outside this list without explicit permission.
Do not modify victron_collector.py — it is a Phase 2 deliverable.
Fixture files in tests/fixtures/ are pre-generated — read them, do not regenerate.

---

## Step 1 — Read first

Before writing any code, read:
- `projects/solar-battery/collector/victron_collector.py`
- `projects/solar-battery/dashboard/app.py`
- `projects/power-dashboard/dashboard/app.py` — reference for all Flask patterns
- `shared/db/influx.py` — InfluxDB wrapper to use

---

## Step 2 — InfluxDB schema

Create `projects/solar-battery/config/schema.md`.

Primary measurement — solar_readings:
```
tags:    device (cerbo), portal_id, source (victron_cerbo)
fields:
  pv_power_w          float   total PV output watts
  pv_yield_today_kwh  float   cumulative kWh since midnight
  battery_soc_pct     float   state of charge 0–100
  battery_power_w     float   positive=charging, negative=discharging
  battery_voltage_v   float
  battery_current_a   float
  grid_power_w        float   positive=import, negative=export
  ac_load_w           float   total AC consumption
  inverter_output_w   float   VE.Bus AC output
  mppt_state          int     0=off 2=fault 3=bulk 4=absorption 5=float
time:    nanosecond precision
```

Secondary — energy_totals (shared with power-dashboard, do not redefine):
```
solar_export_kwh  float  written by Phase 2 collector
```

Document null handling, retention recommendation, and tag cardinality rationale.

---

## Step 3 — Config file

Create `projects/solar-battery/config/solar_collector.yaml`:

```yaml
# Solar battery collector config
# Phase 1 — Cerbo GX hardware not yet installed
# Fill portal_id and mqtt_host when Cerbo GX is on the network
# portal_id: VRM portal → Settings → General
#             or Cerbo GX screen → Settings → VRM online portal → Portal ID
# mqtt_host:  local IP of Cerbo GX (check router DHCP table)

cerbo:
  portal_id: "REPLACE_WITH_PORTAL_ID"
  mqtt_host: "REPLACE_WITH_CERBO_IP"
  mqtt_port: 1883
  keepalive_interval: 60

hardware:
  mppt_count: 1
  topology: hybrid
  battery_type: third_party_lifepo4
  battery_spec: "2x12V 200Ah LifePO4 with integrated BMS"

influxdb:
  bucket: solar
  org: homelab

collection:
  poll_log_interval: 300
```

---

## Step 4 — Flask API routes

Add to `projects/solar-battery/dashboard/app.py`.
Do not modify or remove any existing routes.
Follow power-dashboard exception handling patterns exactly.

```
GET /api/solar/summary
    Latest solar_readings record.
    Returns all fields + mppt_state_label + data_available.
    mppt_state_label: 0=Off, 2=Fault, 3=Bulk, 4=Absorption, 5=Float
    No data → 200, data_available: false, numeric fields null.

GET /api/solar/battery
    Last 24h, sampled every 5 minutes.
    Returns [{time, soc_pct, power_w, voltage_v, current_a}]
    Empty list when no data.

GET /api/solar/pv
    Last 7 days of PV yield.
    Returns [{date, yield_kwh}]

GET /api/solar/history
    Param: days (default 30, max 365)
    Returns [{date, pv_yield_kwh, grid_import_kwh, grid_export_kwh,
              avg_battery_soc_pct, peak_pv_power_w}]
    Invalid days → 400

GET /api/solar/status
    Returns {data_available, last_seen_minutes_ago,
             cerbo_online, mppt_online, inverter_online}
    cerbo_online: last record < 5 min ago.
    All false when InfluxDB empty.
```

Exception rule — no exceptions:
```python
except ValueError as exc:
    app.logger.warning("Bad request: %s", exc)
    return jsonify({"error": "invalid input"}), 400
except Exception as exc:
    app.logger.error("InfluxDB error: %s", exc, exc_info=True)
    return jsonify({"error": "InfluxDB unavailable"}), 503
```

---

## Step 5 — Dashboard template

Update `projects/solar-battery/dashboard/templates/index.html`.
React + Babel via CDN. Fetch from /api/solar/*. Refresh every 30s.

Required panels:
1. Summary strip — PV power (W), Battery SOC (%), Grid flow (W), AC load (W)
2. Battery panel — SOC fill visualization, charge/discharge direction,
   voltage, current, estimated time to full/empty
3. PV panel — today's yield (kWh), current output (W), MPPT state badge
   (Bulk=blue, Absorption=amber, Float=green, Fault=red, Off=gray)
4. Grid panel — import/export value, directional indicator, 7-day summary
5. System status panel — Cerbo online badge, MPPT state, last updated

Placeholder state when data_available is false:
- Numeric values shown as "—" not 0
- Info banner: "Waiting for Cerbo GX — collector will populate data
  when hardware is connected"
- All panels visible — do not hide or collapse
- cerbo_online badge in gray, not red

---

## Step 6 — Dev server for UI testing

Create `projects/solar-battery/tests/dev_server.py`.

A standalone Flask dev tool. Reads fixture files, serves /api/solar/*
with the same JSON shapes as the real app, and adds a scenario endpoint
for testing each dashboard UI state. Never imported by production code.

Add this comment block at the top:
```python
# dev_server.py — Solar battery UI development server
# Serves /api/solar/* routes from pre-generated fixture files.
# Use for UI testing without InfluxDB or Cerbo GX hardware.
#
# Run:  cd projects/solar-battery && python -m tests.dev_server
# Open: http://localhost:5003
#
# Test UI states via the scenario endpoint:
#   GET /api/solar/scenario?name=low_battery
#   GET /api/solar/scenario?name=charging
#   GET /api/solar/scenario?name=cloudy
#   GET /api/solar/scenario?name=night
#   GET /api/solar/scenario?name=fault
# Refresh the dashboard after each to see the state change.
#
# NOT for production use. Not covered by the test suite.
```

Implementation:
- Load all fixture files from tests/fixtures/ on startup into memory
- Serve /api/solar/summary from solar_summary_latest.json
- Serve /api/solar/battery from battery_history.json
- Serve /api/solar/pv from last 7 rows of energy_totals.csv
- Serve /api/solar/history from energy_totals.csv
- Serve /api/solar/status derived from summary (cerbo_online: true,
  last_seen_minutes_ago: 1 — fixture data is always fresh)
- Serve the real dashboard template at / (reuse templates/ directory)
- Run on port 5003

Scenario endpoint:
```
GET /api/solar/scenario?name=<scenario>
```
Overrides the in-memory summary with preset values. Returns updated summary.
Subsequent /api/solar/summary calls return the scenario state until restart.
Unknown scenario name → 400 + {"error": "unknown scenario", "available": [...]}

Scenario presets:
```python
SCENARIOS = {
    "low_battery": {"battery_soc_pct": 12.5, "battery_power_w": -180.0,
                    "mppt_state": 0, "mppt_state_label": "Off",
                    "pv_power_w": 0.0},
    "charging":    {"battery_soc_pct": 67.0, "battery_power_w": 820.0,
                    "mppt_state": 3, "mppt_state_label": "Bulk",
                    "pv_power_w": 1050.0},
    "cloudy":      {"battery_soc_pct": 45.0, "battery_power_w": 95.0,
                    "mppt_state": 3, "mppt_state_label": "Bulk",
                    "pv_power_w": 180.0},
    "night":       {"battery_soc_pct": 55.0, "battery_power_w": -220.0,
                    "mppt_state": 0, "mppt_state_label": "Off",
                    "pv_power_w": 0.0},
    "fault":       {"battery_soc_pct": 38.0, "battery_power_w": 0.0,
                    "mppt_state": 2, "mppt_state_label": "Fault",
                    "pv_power_w": 0.0},
}
```

---

## Step 7 — Tests: test_app.py

Minimum 40 tests. Flask test client. Mock InfluxDB.

/api/solar/summary: happy path, all 6 mppt_state_labels, no data → 200,
  data_available: false, InfluxDB unavailable → 503
/api/solar/battery: happy path, empty → [], InfluxDB → 503
/api/solar/pv: happy path, partial data, InfluxDB → 503
/api/solar/history: default days, custom days, days=0 → 400,
  days=-1 → 400, days=abc → 400, InfluxDB → 503
/api/solar/status: fresh data, stale data, mppt_state 0 and 3,
  no data, InfluxDB → 503

---

## Step 8 — Verification

```bash
python -m py_compile projects/solar-battery/dashboard/app.py
python -m py_compile projects/solar-battery/tests/dev_server.py

.venv/bin/python -m pytest projects/solar-battery/tests/test_app.py -v --tb=short
.venv/bin/python -m pytest projects/power-dashboard/tests/ -v --tb=short
.venv/bin/python -m pytest projects/water-monitor/tests/ -v --tb=short
```

Confirm dev server starts cleanly:
```bash
cd projects/solar-battery
timeout 5 .venv/bin/python -m tests.dev_server || true
```
(timeout is expected — just confirm no import errors)

Targets:
- solar-battery test_app.py: 40+ passing
- power-dashboard: 160 passing
- water-monitor: 124 passing

---

## Constraints

- victron_collector.py must not be modified
- dev_server.py is a dev tool — never imported by production code
- Dashboard shows placeholder state gracefully when InfluxDB empty
- No str(exc) or {exc} inside any jsonify() call
- No print() — use app.logger
- No hardcoded portal_id, IP, or credentials in Python source
- Follow power-dashboard patterns exactly

---

## Completion summary

Provide:
1. Files created or modified with line counts
2. Test count: test_app.py total
3. Confirm all three test suites pass
4. Confirm victron_collector.py not modified
5. Confirm dev_server.py starts without import errors
6. Any InfluxDB Flux query assumptions for empty-data handling
7. Suggested Phase 2 branch name: feature/solar-battery-victron-collector

Then update AGENTS.md:
- Add solar-battery Phase 1 to completed roadmap
- Add Phase 2 to active roadmap with Cerbo GX hardware blocker noted
- Update branch state table
- Note battery: third-party LifePO4 2×12V 200Ah, BMS-limited telemetry
- Note dev server: cd projects/solar-battery && python -m tests.dev_server
