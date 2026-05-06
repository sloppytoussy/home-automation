# Task: power-dashboard-collector

**Branch:** `feature/power-dashboard-collector`
**Scope:** `projects/power-dashboard/` only

Allowed files to create or modify:
```
projects/power-dashboard/collector/mqtt_collector.py   CREATE
projects/power-dashboard/collector/victron_collector.py CREATE (stub only)
projects/power-dashboard/collector/main.py             CREATE or MODIFY
projects/power-dashboard/dashboard/app.py              MODIFY (add routes only)
projects/power-dashboard/dashboard/calculator.py       CREATE
projects/power-dashboard/config/power_collector.yaml   CREATE
projects/power-dashboard/config/schema.md              CREATE
projects/power-dashboard/tests/test_calculator.py      CREATE
projects/power-dashboard/tests/test_collector.py       CREATE
projects/power-dashboard/tests/test_app.py             MODIFY (add tests only)
AGENTS.md                                              MODIFY (session close only)
```

Do not touch any file outside this list without explicit permission.

---

## Context

Two data sources feed the power dashboard and must coexist:

1. **Manual entry** — existing Flask routes. Do not modify. These are the
   authoritative verification layer against the Landis+Gyr utility meter.
2. **MQTT collection** — new. Shelly Pro 3EM (mains, 3-phase) and IotaWatt
   (circuit-level, 14 CT inputs). Both local-first, no cloud.

Solar/Victron is a future phase. Stub the collector file and leave
`solar_export_kwh` fields at `0.0` defaults everywhere.

---

## Step 1 — Read first

Do not write any code until you have read:
- `projects/water-monitor/collector/mqtt_collector.py`
- `projects/power-dashboard/dashboard/app.py`
- `projects/power-dashboard/collector/writer.py`
- `shared/db/influx.py`
- `shared/mqtt/client.py`

---

## Step 2 — InfluxDB schema

Create `projects/power-dashboard/config/schema.md`.

Measurements:
- `power_readings` — per-poll circuit data
- `energy_totals` — daily rollups with `solar_export_kwh` stub field
- `verification_log` — manual vs automated delta tracking
- `solar_readings` — stub measurement, not populated this session

---

## Step 3 — MQTT collector

Create `projects/power-dashboard/collector/mqtt_collector.py`.

Pattern: `water-monitor/collector/mqtt_collector.py` threading model.

Device support:
- **Shelly Pro 3EM** — scalar float payload, topics:
  `shellies/{id}/emeter/{0|1|2}/{power|energy|voltage|current|pf}`
- **IotaWatt** — JSON payload `{"value": float, "units": str}`, topics:
  `iotawatt/{id}/sensor/{name}/{value|wh}`
  Also supports REST `/query` endpoint — poll interval configurable.

Device-agnostic: all topic patterns and circuit mappings come from
`config/power_collector.yaml`. No device logic hardcoded in Python.

Buffer: 100 readings max. On overflow drop oldest, log warning.

---

## Step 4 — Calculator

Create `projects/power-dashboard/dashboard/calculator.py`.

Stdlib only. No I/O. Five functions:

| Function | Key behaviour |
|---|---|
| `calculate_tiered_cost` | RWF tiered rate, returns tier_breakdown list |
| `calculate_net_consumption` | Handles solar_export_kwh stub (default 0.0) |
| `load_breakdown` | Sorted by watts desc, pct_of_total sums to 100 |
| `detect_variance` | Flags when abs(delta_pct) > threshold (default 2%) |
| `project_monthly` | Confidence: low <5d, medium <15d, high >=15d |

All raise `ValueError` with descriptive message on invalid input.

---

## Step 5 — Flask routes

Add to `projects/power-dashboard/dashboard/app.py` (add only, never modify
existing routes):

```
POST /api/calculator/bill-estimate
GET  /api/calculator/net-consumption
GET  /api/calculator/load-breakdown
GET  /api/calculator/variance
POST /api/calculator/projection
```

HTTP 400 on bad input. HTTP 503 on InfluxDB failure.

---

## Step 6 — Victron stub

Create `projects/power-dashboard/collector/victron_collector.py`.
Comment block only — see `.claude/prompts/power-dashboard-collector.md`
for the full topic list and keep-alive requirement to document.

---

## Step 7 — Tests

| File | Minimum | Focus |
|---|---|---|
| `test_calculator.py` | 45 | Pure unit tests, no mocks needed |
| `test_collector.py` | 35 | Mock paho, requests, shared.db.influx |
| `test_app.py` (additions) | 25 | Flask test client, mock InfluxDB |

Total target: 105+

---

## Step 8 — Verification

```bash
# Syntax check
python -m py_compile projects/power-dashboard/dashboard/calculator.py
python -m py_compile projects/power-dashboard/collector/mqtt_collector.py
python -m py_compile projects/power-dashboard/dashboard/app.py

# Full test run
python -m pytest projects/power-dashboard/tests/ -v --tb=short

# Confirm water-monitor not broken
python -m pytest projects/water-monitor/tests/ -v --tb=short
```

All must pass before finalising.

---

## Completion summary

Provide:
1. Files created or modified with line counts
2. Test count: calculator / collector / app / total
3. Any Shelly or IotaWatt payload assumptions made
4. Any InfluxDB tag cardinality concerns
5. Confirmation `victron_collector.py` stub exists
6. Suggested branch name for solar session

Then update `AGENTS.md` per the session close instructions in
`instructions.md` and commit.
