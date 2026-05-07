# Task: Water Monitor — Dev Server

## Branch
`feature/water-monitor-dev-server`

## Base
Cut from `main` at `10b76db`.

## Context
The water monitor dashboard (`dashboard/app.py`) talks directly to InfluxDB.
Without a running InfluxDB instance seeded with data, the dashboard shows
zeros and "no reading" everywhere. This task adds a dev server with fixture
data — the same pattern used in `projects/solar-battery/tests/dev_server.py`
— so the dashboard can be demoed and UI-tested without any live infrastructure.

Reference implementation: `projects/solar-battery/tests/dev_server.py`

---

## Tanks (from config/tanks.yaml)

Tank1: WASAC Mains Tank — 5,000 L, single source (mains), no_outlet overflow
Tank2: Rainwater / WASAC Tank — 14,700 L, dual source (rain + mains), open_outlet
Combined capacity: 19,700 L

---

## Files to create

### 1. `projects/water-monitor/tests/fixtures/tanks_normal.json`
Fixture for the normal operating scenario. Shape must match `/api/tanks` response
(dashboard/app.py lines 265-287). Include for each tank:
id, name, capacity_liters, sources, active_source, level_pct, volume_liters,
depth_cm, water_depth_cm, drain_rate_lph, days_remaining, todays_use_liters,
status, last_updated, pump (name, state, runtime_today_min, last_seen_min),
sensor (battery_pct, last_seen_min).

Realistic values: tank1 at 72% (3,600 L), tank2 at 54% (7,938 L).
tank2 active_source: "rain".

### 2. `projects/water-monitor/tests/fixtures/consumption_history.json`
90 days of daily consumption for `/api/consumption?days=90`.
Dates from 2026-02-06 through 2026-05-06.
Format: [{"time": "2026-02-06T00:00:00+00:00", "value": 154.2}, ...]
Realistic values: 120-180 L/day with occasional zero days (sensor offline).

### 3. `projects/water-monitor/tests/fixtures/level_history_tank1.json`
7 days of hourly level readings for `/api/history/tank1`.
Format: [{"time": "...", "value": <volume_liters>}, ...]
Gradual decline from ~3,750 L to ~3,600 L with realistic noise.

### 4. `projects/water-monitor/tests/fixtures/level_history_tank2.json`
Same for tank2. Decline from ~8,820 L to ~7,938 L over 7 days.

### 5. `projects/water-monitor/tests/dev_server.py`
Standalone Flask app on port 5001. Serves fixture data for all dashboard routes.
Does NOT import or wrap dashboard/app.py — it is its own Flask app.
Sets template_folder to ../dashboard/templates to serve index.html.

Scenarios (6 total) via GET /api/water/scenario?name=<name>:
- normal: both tanks healthy, tank1 72%, tank2 54%
- low_tank1: tank1 at 18% (below 20% low threshold), tank2 normal
- low_both: both tanks critically low, tank1 <15%, tank2 <15%
- filling: tank1 filling (drain_rate_lph negative ~-45), pump state "running"
- full: both tanks at 95%+ (near overflow threshold)
- sensor_offline: both sensors last_seen_min > 60, status "stale"

Routes:
  GET  /                        serve index.html via render_template
  GET  /api/tanks               return current scenario tank fixture
  GET  /api/history/<tank_id>   return level_history_tank1.json or tank2
  GET  /api/consumption         return consumption_history.json (accepts ?days=)
  POST /api/source/<tank_id>    update active_source in memory, return
                                {"tank_id": ..., "active_source": ...}
                                400 if source not in tank's sources list
  GET  /api/water/scenario      apply named scenario, 400 if unknown

Scenario overlay: load tanks_normal.json as base dict, apply named deltas
to level_pct, volume_liters, status, drain_rate_lph, pump.state,
sensor.last_seen_min as needed. /api/tanks always returns current state.

Startup print must show port 5001 and all 6 scenario names.

---

## Testing

### `projects/water-monitor/tests/test_dev_server.py`
Target: 30+ tests.

Required cases:
- All 6 scenario names return 200 with 2 tanks in response
- Unknown scenario returns 400 with "available" key listing all 6
- /api/tanks returns both tanks with all required fields present
- /api/history/tank1 and /api/history/tank2 return non-empty lists
- /api/consumption returns list with ~90 entries
- POST /api/source/tank2 body {"source": "mains"} returns 200,
  active_source updates to "mains"
- POST /api/source/tank2 body {"source": "invalid"} returns 400
- POST /api/source/tank1 body {"source": "rain"} returns 400
  (tank1 only has mains)
- low_tank1 scenario: tank1 level_pct < 20
- low_both scenario: both tanks level_pct < 15
- full scenario: both tanks level_pct >= 95
- filling scenario: tank1 drain_rate_lph < 0
- sensor_offline scenario: both sensors last_seen_min > 60
- normal scenario: both tanks level_pct > 50
- GET / returns 200 (dashboard HTML loads)

### All existing suites must still pass
- Water: 124 existing + 30 new = 154+ total
- Solar: 122 unchanged
- Power: 160 unchanged

Run:
  .venv/bin/python -m pytest projects/water-monitor/tests/ -v --tb=short
  .venv/bin/python -m pytest projects/solar-battery/tests/ -v --tb=short
  .venv/bin/python -m pytest projects/power-dashboard/tests/ -v --tb=short

---

## Constraints
- Use .venv/bin/python — never bare python
- docker-compose hyphenated if any compose references added
- No co-author lines in commits
- No live InfluxDB or hardware calls in dev server or tests
- Fixture JSON files must be valid — verify with:
  .venv/bin/python -m json.tool tests/fixtures/tanks_normal.json

---

## Verification checklist
- [ ] tests/dev_server.py starts on port 5001 without errors
- [ ] All 6 scenarios return correct shape for both tanks
- [ ] POST /api/source/<tank_id> updates in-memory active_source
- [ ] Dashboard renders at http://127.0.0.1:5001 with fixture data visible
- [ ] test_dev_server.py has 30+ tests, all passing
- [ ] Water suite total >= 154 tests
- [ ] Solar (122) and Power (160) unchanged
- [ ] No bare python, no docker compose (unhyphenated)
- [ ] No co-author lines in git log
