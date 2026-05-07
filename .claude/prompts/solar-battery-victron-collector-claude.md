# Claude Review: Solar Battery — Victron Collector (Phase 2)

## Branch
`feature/solar-battery-victron-collector`

## What Codex built
Three parallel collectors (MQTT primary, Modbus fallback, Solarman) writing
live Cerbo GX data to InfluxDB, plus two P2 bug fixes from the Phase 1 review.

---

## P2 fixes to verify first

### Fix 1 — Dual-write in SolarWriter
`collector/writer.py` must write both `Point("solar")` and
`Point("solar_readings")` in every `write_reading` call.

Check:
```bash
grep -n "solar_readings\|Point(" projects/solar-battery/collector/writer.py
```
Expect two `Point(...)` calls per write. If only one measurement is written,
the dashboard still returns placeholders when live data is present.

### Fix 2 — aggregateWindow date alignment
`dashboard/app.py` functions `pv_yield_history()` and `daily_energy_history()`
must include `timeSrc: "_start"` in their `aggregateWindow` Flux calls.

Check:
```bash
grep -n "timeSrc\|aggregateWindow" projects/solar-battery/dashboard/app.py
```
Expect `timeSrc: "_start"` on both occurrences. If missing, every bar in the
PV history chart is shifted one day forward on real data.

---

## Collector review checklist

### Structure
```bash
ls projects/solar-battery/collector/
# expect: __init__.py main.py modbus_collector.py mqtt_collector.py
#         solarman_collector.py writer.py
```

### Backoff implementation
All three collectors must use exponential backoff (base 2s, max 60s).
```bash
grep -n "backoff\|sleep\|retry" projects/solar-battery/collector/mqtt_collector.py
grep -n "backoff\|sleep\|retry" projects/solar-battery/collector/modbus_collector.py
grep -n "backoff\|sleep\|retry" projects/solar-battery/collector/solarman_collector.py
```
If any collector retries with a fixed sleep or no sleep, flag it.

### Timeout protection
Every network call must have a timeout — no blocking indefinitely.
```bash
grep -n "timeout" projects/solar-battery/collector/mqtt_collector.py
grep -n "timeout" projects/solar-battery/collector/modbus_collector.py
grep -n "timeout" projects/solar-battery/collector/solarman_collector.py
```

### No bare python, no docker compose (unhyphenated)
```bash
grep -rn "^python \|subprocess.*[\"']python \| docker compose " \
  projects/solar-battery/ --include="*.py" --include="*.sh" --include="*.md"
```
Must return empty.

### No co-author lines
```bash
git log feature/solar-battery-victron-collector ^main --format="%B" | \
  grep -i "co-author\|claude\|anthropic\|openai\|codex"
```
Must return empty.

---

## Test review checklist

### Test counts
```bash
.venv/bin/python -m pytest projects/solar-battery/tests/ -v --tb=short 2>&1 | tail -5
.venv/bin/python -m pytest projects/power-dashboard/tests/ -v --tb=short 2>&1 | tail -5
.venv/bin/python -m pytest projects/water-monitor/tests/ -v --tb=short 2>&1 | tail -5
```
- Solar: ≥ 200 (122 Phase 1 + 80+ new)
- Power: 160 (unchanged)
- Water: 124 (unchanged)

### No live hardware in tests
```bash
grep -n "192\.168\.\|connect(\|real.*hardware" \
  projects/solar-battery/tests/test_collector.py
```
All hardware calls must go through `unittest.mock.patch`. Any unpatched
network connection is a test environment failure.

### Dual-write regression test
```bash
grep -n "solar_readings\|assert.*call" \
  projects/solar-battery/tests/test_collector.py | head -20
```
Must see assertions that `write_api.write` (or equivalent) is called with
both `solar` and `solar_readings` measurement names in a single
`write_reading` invocation.

### aggregateWindow date regression test
```bash
grep -n "timeSrc\|2026-05-06\|off.by.one\|date" \
  projects/solar-battery/tests/test_app.py | head -20
```
Must see at least one test asserting that fixture data for a given day returns
that same day's date string, not the next day.

---

## Documentation check
```bash
ls projects/solar-battery/docs/
# expect: measurement-names.md  collector-setup.md
```

`measurement-names.md` must contain:
- Rationale for dual-write
- Field name mapping table (writer field → MQTT topic → Modbus register)
- Deprecation plan for `Point("solar")`

`collector-setup.md` must contain:
- Cerbo GX MQTT broker enable steps
- Cerbo GX Modbus TCP enable steps
- All env var names and defaults

---

## Docker check
```bash
grep -n "collector\|depends_on\|unless-stopped" \
  projects/solar-battery/docker-compose.yml
```
Must see a `collector` service with `depends_on: influxdb` and
`restart: unless-stopped`.

---

## Common issues to watch for

**MQTT field mapping gaps** — Victron MQTT topic names do not map 1:1 to
the writer's field names. Check that every `SolarWriter` field has a
corresponding topic subscription. Missing fields should be logged as warnings,
not silently dropped or written as zero.

**Modbus scale factors** — Register 840 (SOC) is scale /10, register 259
(voltage) is /100. Confirm the collector applies the correct divisor for each
register. Off-by-10x errors are common here.

**Thread safety in main.py** — When `--collector all` runs three threads,
each thread gets its own `SolarWriter` instance (or the shared instance is
thread-safe). Check that InfluxDB write calls are not racing.

**Solarman local API** — This is the local LAN endpoint, not the cloud API.
The URL must be configurable and default to the local host. Confirm no
cloud.solarmanpv.com hardcoded URLs appear.

---

## Sign-off criteria
All of the following must be true before approving PR:

- [ ] Fix 1 confirmed: dual-write in writer.py
- [ ] Fix 2 confirmed: timeSrc: "_start" in both history functions
- [ ] Three collectors present with backoff + timeout + SIGTERM
- [ ] main.py --collector all starts three threads
- [ ] Solar tests ≥ 200, all passing
- [ ] Power 160 and Water 124 unchanged
- [ ] No live hardware calls in tests
- [ ] Dual-write and date regression tests present
- [ ] docs/measurement-names.md and docs/collector-setup.md present
- [ ] docker-compose.yml has collector service
- [ ] No bare python, no docker compose (unhyphenated)
- [ ] No co-author lines in git log
