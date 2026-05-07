# Task: Solar Battery — Victron Collector (Phase 2)

## Branch
`feature/solar-battery-victron-collector`

## Base
Cut from `main` after PR #4 merge.

## Context
Phase 1 delivered the dashboard, dev server, and 122 tests with no hardware
dependency. Phase 2 implements the live data pipeline: three collectors running
in parallel (MQTT primary, Modbus fallback, Solarman) writing to InfluxDB, plus
two known P2 fixes carried forward from the Phase 1 review.

Hardware arriving: Cerbo GX (Victron). Battery: third-party LiFePO4 2×12V 200Ah,
BMS-limited telemetry — do not assume full BMS field availability.

---

## P2 Fixes (implement these first, before any new collector work)

### Fix 1 — Measurement name mismatch
`SolarWriter.write_reading` writes `Point("solar")` with fields like
`load_power_w` and `daily_yield_kwh`. The Phase 1 dashboard queries
`solar_readings`. With a live collector, the dashboard returns placeholders
even while fresh data is present in InfluxDB.

**Resolution:** Update `SolarWriter.write_reading` to write both measurements
in every call — `Point("solar")` (existing, unchanged) and `Point("solar_readings")`
(new, same fields). This allows the dashboard to read `solar_readings` while
any legacy consumers of `solar` continue to work. Document the dual-write
decision in `projects/solar-battery/docs/measurement-names.md`.

### Fix 2 — aggregateWindow off-by-one day
In `dashboard/app.py`, the Flux query for daily PV history uses
`aggregateWindow(every: 1d, ...)` which assigns `_time` from the window stop
by default. May 6 data is returned with a May 7 timestamp, shifting every
bar in the chart one day forward.

**Resolution:** Add `timeSrc: "_start"` to the `aggregateWindow` call in
`pv_yield_history()` and `daily_energy_history()`. Regression-test with
existing fixture data to confirm dates are correct.

---

## Collector Implementation

### Shared requirements for all three collectors
- Live in `projects/solar-battery/collector/`
- Accept config from `projects/solar-battery/config/solar_collector.yaml`
- Use `SolarWriter` from `collector/writer.py` — do not bypass it
- On successful read, write via `SolarWriter.write_reading` (dual-write now handled by writer)
- Implement exponential backoff on connection failure (base 2s, max 60s, jitter)
- Structured logging via `shared/logger.py` — no bare `print()`
- Strict timeout on every network call (configurable, default 10s)
- Graceful shutdown on SIGTERM

### mqtt_collector.py (PRIMARY)
- Connect to Victron MQTT broker on Cerbo GX (default port 1883)
- Subscribe to Victron MQTT topics:
  - `N/<vrm_id>/system/0/Dc/Battery/Soc` — battery SOC %
  - `N/<vrm_id>/system/0/Dc/Battery/Voltage` — battery voltage V
  - `N/<vrm_id>/system/0/Dc/Battery/Current` — battery current A
  - `N/<vrm_id>/system/0/Dc/Battery/Power` — battery power W
  - `N/<vrm_id>/system/0/Dc/Pv/Power` — PV power W
  - `N/<vrm_id>/system/0/Ac/Consumption/Total/Power` — load power W
  - `N/<vrm_id>/vebus/276/State` — inverter/MPPT state
  - `N/<vrm_id>/solarcharger/0/Yield/Power` — PV yield today kWh
- Parse JSON payloads (`{"value": ...}` envelope)
- Map to `SolarWriter` field names (see `config/solar_collector.yaml`)
- `vrm_id` read from config or `VICTRON_VRM_ID` env var
- Use `paho-mqtt` (already in requirements.txt)
- Reconnect loop with backoff on disconnect

### modbus_collector.py (FALLBACK)
- Connect to Cerbo GX Modbus TCP (default port 502, unit ID 100)
- Poll registers on configurable interval (default 10s)
- Register map (Victron Cerbo GX Modbus register list):
  - 840 — battery SOC (scale /10, %)
  - 259 — battery voltage (scale /100, V)
  - 261 — battery current (scale /10, A)
  - 258 — battery power (W)
  - 850 — PV power (W)
  - 817 — AC consumption (W)
  - 843 — MPPT state
- Use `pymodbus` (already in requirements.txt)
- On read failure, log warning and retry after backoff — do not write partial rows

### solarman_collector.py
- Connect to Solarman dongle via local LAN API (not cloud)
- Endpoint: `http://<host>/real_time_data` (configurable)
- Poll on configurable interval (default 30s)
- Map response fields to `SolarWriter` field names per `config/solar_collector.yaml`
- Handle HTTP timeout and non-200 responses with backoff
- Use `requests` library

### collector/main.py
- Parse `--collector` flag: `mqtt`, `modbus`, `solarman`, or `all`
- `all` runs all three in separate threads with independent backoff loops
- Log which collectors are active at startup
- SIGTERM handler stops all threads cleanly

---

## Configuration

Update `projects/solar-battery/config/solar_collector.yaml` to include:

```yaml
mqtt:
  host: "192.168.1.x"        # Cerbo GX IP
  port: 1883
  vrm_id: ""                  # override with VICTRON_VRM_ID env var
  keepalive: 60
  timeout: 10

modbus:
  host: "192.168.1.x"        # Cerbo GX IP
  port: 502
  unit_id: 100
  poll_interval: 10
  timeout: 10

solarman:
  host: "192.168.1.x"
  port: 80
  poll_interval: 30
  timeout: 10

influxdb:
  url: ""                     # override with INFLUXDB_URL env var
  token: ""                   # override with INFLUXDB_TOKEN env var
  org: ""                     # override with INFLUXDB_ORG env var
  bucket: ""                  # override with INFLUXDB_BUCKET env var
```

---

## Testing

Target: 80+ new tests in `tests/test_collector.py` (total solar suite ≥ 200).

### Required test coverage
- `mqtt_collector.py`: mock paho-mqtt client, test topic subscription,
  JSON payload parsing, field mapping, reconnect on disconnect, backoff timing
- `modbus_collector.py`: mock pymodbus client, test register reads,
  scale factor application, partial read failure handling, backoff
- `solarman_collector.py`: mock `requests`, test happy path, timeout,
  non-200 response, malformed JSON
- `writer.py` dual-write: assert both `Point("solar")` and
  `Point("solar_readings")` are written in a single `write_reading` call
- `main.py`: test `--collector all` spawns three threads, SIGTERM shuts
  down cleanly
- Fix regression tests:
  - `aggregateWindow` date fix: fixture data for May 6 returns date "2026-05-06"
    not "2026-05-07"
  - Dual-write: mock InfluxDB write client, assert called twice per reading

### Standards
- Use `unittest.mock.patch` for all hardware and network calls
- No live hardware required — all tests must pass without Cerbo GX present
- Use `.venv/bin/python -m pytest` — never bare `python`
- Exponential backoff: mock `time.sleep`, assert called with correct delays

---

## Docker

Update `projects/solar-battery/docker-compose.yml`:
- Add `collector` service running `collector/main.py --collector all`
- Environment variables for InfluxDB and MQTT credentials (no hardcoded secrets)
- `depends_on: influxdb`
- Restart policy: `unless-stopped`

---

## Documentation

- `projects/solar-battery/docs/measurement-names.md` — dual-write rationale,
  field name mapping table, deprecation plan for `Point("solar")`
- `projects/solar-battery/docs/collector-setup.md` — Cerbo GX network config,
  MQTT broker enable steps, Modbus TCP enable steps, env var reference
- Update `projects/solar-battery/README.md` — Phase 2 status, collector usage

---

## Verification checklist
- [ ] Fix 1: `SolarWriter.write_reading` writes both `solar` and `solar_readings`
- [ ] Fix 2: `aggregateWindow` uses `timeSrc: "_start"` in both history functions
- [ ] All three collectors implement backoff, timeout, and SIGTERM handling
- [ ] `main.py --collector all` starts three threads
- [ ] `tests/test_collector.py` exists with 80+ tests, no live hardware required
- [ ] Solar suite total ≥ 200 tests
- [ ] Water (124) and Power (160) suites still pass
- [ ] `docker-compose.yml` includes collector service
- [ ] No bare `python`, no `docker compose` (unhyphenated)
- [ ] No co-author lines in commits
- [ ] `docs/measurement-names.md` and `docs/collector-setup.md` created
