# Solar battery — Phase 1: dashboard, API routes, and dev server

**Branch:** `feature/solar-battery-phase1-dashboard`
**Prerequisite:** Run `session-open.md` before starting.

---

## Situation

The Victron Cerbo GX hardware has not been purchased yet. This session
builds everything that does not require the hardware:

- InfluxDB schema definition
- Flask API routes with graceful empty-data handling
- Solar dashboard UI
- Dev server for UI testing without InfluxDB or hardware
- Full test suite against mocked InfluxDB

The collector (victron_collector.py) is already stubbed. Do not touch it.
When the Cerbo GX arrives, Phase 2 replaces the stub. The schema, routes,
dashboard, and dev server built here will not change in Phase 2.

---

## Hardware context

- Cerbo GX: not yet purchased
- Battery: third-party LifePO4 2×12V 200Ah with integrated BMS
- BMS telemetry: SOC, voltage, current, power only — no cell-level data
- MPPT charge controllers: 1
- Topology: hybrid (grid-tied with battery backup and solar)
- Inverter: Victron VE.Bus (MultiPlus or Quattro)

---

## Step 1 — Read these files first

1. `projects/solar-battery/collector/victron_collector.py` — topic map
   tells you exactly what fields Phase 2 will write. Schema and routes
   must match it precisely.
2. `projects/solar-battery/dashboard/app.py` — what already exists.
3. `projects/power-dashboard/dashboard/app.py` — reference for all
   Flask patterns, safe query helpers, exception handling.
4. `shared/db/influx.py` — InfluxDB wrapper. Always use it.

Also check `projects/solar-battery/tests/fixtures/` — four pre-generated
dummy data files are already there. Read their structure before writing
any Flux queries or dev server code.

---

## Step 2 — InfluxDB schema

Create `projects/solar-battery/config/schema.md`.

Primary measurement — `solar_readings`:
```
tags:    device (cerbo), portal_id, source (victron_cerbo)
fields:
  pv_power_w          float   total PV output watts
  pv_yield_today_kwh  float   cumulative kWh since midnight (all MPPTs)
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

Secondary — `energy_totals` (shared with power-dashboard):
```
solar_export_kwh  float  Phase 2 collector writes this from Daily Yield
                          field already exists in power-dashboard schema
```

Document:
- Null handling: {"value": null} from Cerbo = offline. Skip write, log.
- Retention: 90-day raw + infinite daily aggregates.
- Tag cardinality: portal_id is low-cardinality, safe as a tag.

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
Copy the safe query helper and exception handling pattern from
`projects/power-dashboard/dashboard/app.py` exactly.

### Route specifications

```
GET /api/solar/summary
    Latest solar_readings record.
    Returns: {pv_power_w, pv_yield_today_kwh, battery_soc_pct,
              battery_power_w, battery_voltage_v, battery_current_a,
              grid_power_w, ac_load_w, inverter_output_w,
              mppt_state, mppt_state_label, last_updated, data_available}
    mppt_state_label: 0=Off, 2=Fault, 3=Bulk, 4=Absorption, 5=Float, else Unknown
    No data → 200, data_available: false, numeric fields null

GET /api/solar/battery
    Last 24h, sampled every 5 minutes.
    Returns: [{time, soc_pct, power_w, voltage_v, current_a}]
    Empty list when no data — not an error.

GET /api/solar/pv
    Last 7 days of PV yield from pv_yield_today_kwh daily last() values.
    Returns: [{date, yield_kwh}]
    Partial data returns what exists.

GET /api/solar/history
    Param: days (default 30, max 365)
    Returns: [{date, pv_yield_kwh, grid_import_kwh, grid_export_kwh,
               avg_battery_soc_pct, peak_pv_power_w}]
    Invalid days → 400 + {"error": "invalid input"}

GET /api/solar/status
    Derived from data freshness.
    Returns: {data_available, last_seen_minutes_ago,
              cerbo_online, mppt_online, inverter_online}
    cerbo_online: last record < 5 min ago
    mppt_online: mppt_state not null and not 0
    inverter_online: inverter_output_w not null
    All false when InfluxDB empty.
```

### Exception handling — no raw exceptions in responses
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
React + Babel via CDN (match power-dashboard versions exactly).
Auto-fetch from /api/solar/* every 30 seconds.

### Required panels

1. Summary strip — four tiles: PV output (W), Battery SOC (%),
   Grid flow (W with import/export direction arrow), AC load (W)

2. Battery panel — SOC fill visualization consistent with water-monitor
   and power-dashboard style. Shows charge/discharge direction, voltage,
   current, and estimated time to full or empty calculated from
   battery_power_w and remaining capacity (4800Wh × remaining SOC%).

3. PV panel — today's yield (kWh), current output (W), MPPT state badge:
   Bulk=blue, Absorption=amber, Float=green, Fault=red, Off=gray

4. Grid panel — current import/export wattage, directional indicator,
   7-day import vs export bar summary

5. System status panel — Cerbo online badge, MPPT state label, last
   updated timestamp

### Placeholder state (data_available: false)
- Show "—" for all numeric values, not 0
- Non-alarming info banner: "Waiting for Cerbo GX — collector will
  populate data when hardware is connected"
- All panels visible — do not hide, collapse, or error
- cerbo_online badge in gray, not red
- This state is expected during Phase 1

---

## Step 6 — Dev server for UI testing

Create `projects/solar-battery/tests/dev_server.py`.

This is a standalone Flask app for testing the dashboard UI without
InfluxDB or the Cerbo GX. Reads fixture files from tests/fixtures/,
serves identical JSON shapes to the real API routes, and adds a scenario
endpoint for switching between preset UI states.

Never imported by production code. Not covered by the test suite.

### Comment block at top of file
```python
# dev_server.py — Solar battery UI development server
# Serves /api/solar/* routes from pre-generated fixture files.
# Use for UI testing without InfluxDB or Cerbo GX hardware.
#
# Run:  cd projects/solar-battery && python -m tests.dev_server
# Open: http://localhost:5003
#
# Switch UI states via the scenario endpoint:
#   GET /api/solar/scenario?name=low_battery
#   GET /api/solar/scenario?name=charging
#   GET /api/solar/scenario?name=cloudy
#   GET /api/solar/scenario?name=night
#   GET /api/solar/scenario?name=fault
# Then refresh the browser to see the change.
#
# NOT for production use. Not covered by the test suite.
```

### Implementation

Load all fixture files on startup into memory:
- `solar_summary_latest.json` → in-memory summary dict (mutable for scenarios)
- `battery_history.json` → battery route data
- `energy_totals.csv` → history and PV route data

Routes to serve (identical JSON shapes to real app):
- `GET /` — serve the real dashboard template from templates/
- `GET /api/solar/summary` — return in-memory summary dict
- `GET /api/solar/battery` — return battery_history fixture
- `GET /api/solar/pv` — last 7 rows of energy_totals as [{date, yield_kwh}]
- `GET /api/solar/history` — energy_totals as history shape
- `GET /api/solar/status` — derive from summary; always cerbo_online: true,
  last_seen_minutes_ago: 1 (fixture data is always fresh)

Scenario endpoint:
```
GET /api/solar/scenario?name=<scenario>
```
Updates the in-memory summary with preset field values.
Returns the updated summary as confirmation.
Unknown name → 400 + {"error": "unknown scenario", "available": [...]}

### Scenario presets
```python
SCENARIOS = {
    "low_battery": {
        "battery_soc_pct": 12.5, "battery_power_w": -180.0,
        "mppt_state": 0, "mppt_state_label": "Off", "pv_power_w": 0.0,
    },
    "charging": {
        "battery_soc_pct": 67.0, "battery_power_w": 820.0,
        "mppt_state": 3, "mppt_state_label": "Bulk", "pv_power_w": 1050.0,
    },
    "cloudy": {
        "battery_soc_pct": 45.0, "battery_power_w": 95.0,
        "mppt_state": 3, "mppt_state_label": "Bulk", "pv_power_w": 180.0,
    },
    "night": {
        "battery_soc_pct": 55.0, "battery_power_w": -220.0,
        "mppt_state": 0, "mppt_state_label": "Off", "pv_power_w": 0.0,
    },
    "fault": {
        "battery_soc_pct": 38.0, "battery_power_w": 0.0,
        "mppt_state": 2, "mppt_state_label": "Fault", "pv_power_w": 0.0,
    },
}
```

Run on port 5003 (matches launch.json solar-battery entry).

---

## Step 7 — Tests: test_app.py

Minimum 40 tests. Flask test client. Mock InfluxDB.

### Required coverage

`/api/solar/summary`:
- Happy path — all expected fields present and correctly typed
- All 6 mppt_state_label values (5 valid + Unknown for unmapped int)
- No data → 200, data_available: false, numeric fields null
- InfluxDB unavailable → 503

`/api/solar/battery`:
- Happy path — [{time, soc_pct, power_w, voltage_v, current_a}]
- Empty InfluxDB → [], 200
- InfluxDB unavailable → 503

`/api/solar/pv`:
- Happy path — 7 days
- Partial data — fewer than 7 days returned correctly
- InfluxDB unavailable → 503

`/api/solar/history`:
- Default 30 days
- Custom days=7
- days=0 → 400
- days=-1 → 400
- days=abc → 400
- InfluxDB unavailable → 503

`/api/solar/status`:
- Fresh data (< 5 min) → cerbo_online: true
- Stale data (> 5 min) → cerbo_online: false
- mppt_state=0 → mppt_online: false
- mppt_state=3 → mppt_online: true
- No data → all false, last_seen_minutes_ago: null
- InfluxDB unavailable → 503

---

## Step 8 — Verification

```bash
python -m py_compile projects/solar-battery/dashboard/app.py
python -m py_compile projects/solar-battery/tests/dev_server.py

.venv/bin/python -m pytest projects/solar-battery/tests/test_app.py -v --tb=short
.venv/bin/python -m pytest projects/power-dashboard/tests/ -v --tb=short
.venv/bin/python -m pytest projects/water-monitor/tests/ -v --tb=short
```

Confirm dev server starts cleanly (timeout expected):
```bash
cd projects/solar-battery
timeout 5 .venv/bin/python -m tests.dev_server || true
```

Targets:
- solar-battery: 40+ tests passing
- power-dashboard: 160 passing — no regression
- water-monitor: 124 passing — no regression

Also verify:
```bash
grep -n "str(exc)\|{exc}" projects/solar-battery/dashboard/app.py
```
Must return zero matches inside jsonify() calls.

---

## Constraints

- Do not modify `collector/victron_collector.py` — Phase 2 deliverable
- `dev_server.py` is a dev tool only — never imported by production code
- Dashboard must show placeholder state when InfluxDB is empty
- No str(exc) or {exc} inside any jsonify() call in app.py
- No print() — use app.logger
- No hardcoded portal_id, IP, or credentials in Python source
- Follow power-dashboard patterns exactly for all Flask code
- All three existing test suites must remain green

---

## How to test the UI after the session

```bash
# Start the dev server
cd projects/solar-battery
python -m tests.dev_server

# Open the dashboard
open http://localhost:5003

# Switch to a UI state and refresh the browser
curl "http://localhost:5003/api/solar/scenario?name=low_battery"
curl "http://localhost:5003/api/solar/scenario?name=fault"
curl "http://localhost:5003/api/solar/scenario?name=charging"
curl "http://localhost:5003/api/solar/scenario?name=night"
curl "http://localhost:5003/api/solar/scenario?name=cloudy"
```

---

## Completion summary

Provide:
1. Files created or modified with line counts
2. Test count: test_app.py total
3. Confirm all three test suites pass
4. Confirm victron_collector.py not modified
5. Confirm dev_server.py starts without import errors
6. Any InfluxDB Flux query assumptions for empty-data handling
7. Phase 2 branch name: `feature/solar-battery-victron-collector`

Then run `session-close.md`.
