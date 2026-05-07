# Task: lighting-phase1

**Branch:** `feature/lighting-phase1`
**Scope:** `projects/lighting-control/` only

## Allowed files to create or modify

```
projects/lighting-control/                                        CREATE (scaffold)
projects/lighting-control/collector/__init__.py                   CREATE
projects/lighting-control/collector/main.py                       CREATE
projects/lighting-control/collector/mqtt_collector.py             CREATE
projects/lighting-control/collector/http_collector.py             CREATE
projects/lighting-control/collector/writer.py                     CREATE
projects/lighting-control/dashboard/__init__.py                   CREATE
projects/lighting-control/dashboard/app.py                        CREATE
projects/lighting-control/dashboard/templates/index.html          CREATE
projects/lighting-control/config/lighting.yaml                    CREATE
projects/lighting-control/config/schema.md                        CREATE
projects/lighting-control/requirements.txt                        CREATE
projects/lighting-control/Dockerfile                              CREATE
projects/lighting-control/tests/__init__.py                       CREATE
projects/lighting-control/tests/test_app.py                       CREATE
projects/lighting-control/tests/test_collector.py                 CREATE
projects/lighting-control/tests/dev_server.py                     CREATE
projects/lighting-control/tests/fixtures/devices_state.json       CREATE
projects/lighting-control/tests/fixtures/rooms_summary.json       CREATE
projects/lighting-control/tests/fixtures/overview.json            CREATE
AGENTS.md                                                         MODIFY (session close only)
```

Do not touch any file outside this list without explicit permission.

---

## Context

Lighting control is the newest sub-project in the home automation platform.
Phase 1 builds the foundation: directory scaffold, Shelly device collection
via MQTT and HTTP, InfluxDB state tracking, Flask device management API,
and a 6-tab dashboard (overview and devices active; remaining tabs as
Phase 2 placeholders).

Hardware target: Shelly Gen1 and Gen2 devices. Local-first — no Shelly cloud.
Mosquitto MQTT broker is already running in the shared Docker stack.

Two collection paths:
1. **MQTT subscriber** — Shelly publishes state topics on every change. Real-time.
2. **HTTP poller** — Periodic poll for initial state at startup and missed events.

HA-compatible output: when `home_assistant.enabled: true` in config, publish
HA MQTT discovery payloads and mirror state to HA topics. Never active by default.

---

## Step 1 — Read first

Before writing any code, read:
- `projects/power-dashboard/collector/mqtt_collector.py`
- `projects/water-monitor/collector/mqtt_collector.py`
- `projects/solar-battery/dashboard/app.py`
- `shared/db/influx.py`
- `shared/mqtt/client.py`

---

## Step 2 — InfluxDB schema

Create `projects/lighting-control/config/schema.md`.

**lighting_state** — written on every state change (MQTT or HTTP)
```
tags:   device_id, room, device_type, generation (gen1|gen2),
        source (mqtt|http|command)
fields: is_on (bool),
        brightness_pct (float — omit if device is not dimmable),
        power_w        (float — omit if no power meter),
        energy_wh      (float cumulative — omit if no power meter),
        temperature_c  (float device temp — omit if unavailable),
        rssi           (int signal strength — omit if unavailable)
time:   nanosecond precision
```

**lighting_events** — discrete on/off/scene/presence/schedule events
```
tags:   device_id, room,
        event_type (on|off|dim|scene|presence|schedule)
fields: triggered_by (string: manual|schedule|scene|presence|api|mqtt),
        brightness_pct (float — omit if not dimmable)
time:   nanosecond precision
```

**lighting_energy** — energy counters, PM-capable devices only
```
tags:   device_id, room
fields: power_w   (float),
        wh_delta  (float — Wh consumed since previous sample),
        wh_total  (float — cumulative counter from device)
time:   nanosecond precision
```

Document: null handling (omit, never write None), retention recommendation
(raw 30 days, daily aggregates infinite), tag cardinality rationale
(`device_id` not `shelly_id`).

---

## Step 3 — Config file

Create `projects/lighting-control/config/lighting.yaml`:

```yaml
mqtt:
  broker_host: localhost
  broker_port: 1883

devices:
  - id: living_room_main
    name: "Living Room Main"
    room: living_room
    type: shellyplus1pm
    generation: gen2
    ip: "REPLACE_WITH_DEVICE_IP"
    shelly_id: "shellyplus1pm-REPLACE"
    dimmable: false
    has_power_meter: true

  - id: bedroom_lamp
    name: "Bedroom Lamp"
    room: bedroom
    type: shelly1
    generation: gen1
    ip: "REPLACE_WITH_DEVICE_IP"
    shelly_id: "shelly1-REPLACE"
    dimmable: false
    has_power_meter: false

rooms:
  - id: living_room
    name: "Living Room"
  - id: bedroom
    name: "Bedroom"
  - id: kitchen
    name: "Kitchen"
  - id: office
    name: "Office"

home_assistant:
  enabled: false
  discovery_prefix: homeassistant

influxdb:
  bucket: lighting
  org: homelab

collection:
  http_poll_interval: 30
  buffer_size: 200
```

---

## Step 4 — MQTT collector

Create `projects/lighting-control/collector/mqtt_collector.py`.

Pattern: `projects/power-dashboard/collector/mqtt_collector.py` threading model.

### Gen1 topic structure
```
shellies/{shelly_id}/relay/0             scalar string "on" or "off"
shellies/{shelly_id}/light/0             JSON {"ison": bool, "brightness": int}
shellies/{shelly_id}/emeter/0/power      scalar float (watts)
shellies/{shelly_id}/emeter/0/energy     scalar float (Wh cumulative)
```

### Gen2 topic structure
```
{shelly_id}/status/switch:0    JSON {"output": bool, "apower": float,
                                     "aenergy": {"total": float}}
{shelly_id}/status/light:0     JSON {"output": bool, "brightness": float}
{shelly_id}/events/rpc         JSON RPC NotifyStatus (mirror of status topics)
```

### Requirements
- Build subscription topic list from config `shelly_id` values — never hardcoded
- Dispatch Gen1 vs Gen2 parsing based on device `generation` field from config
- Map `shelly_id` → `device_id` via config lookup — never use `shelly_id` as tag
- Write `lighting_state` to InfluxDB via `shared/db/influx.py`
- Write `lighting_energy` for devices where `has_power_meter: true`
- Omit null fields entirely from InfluxDB writes — do not write None or 0
- On parse error: log and skip, do not crash
- On InfluxDB write failure: buffer up to 200 readings, retry on reconnect
- On buffer overflow (>200): drop oldest, log warning
- Graceful SIGTERM/SIGINT shutdown
- Structured logging via `shared/` only — no `print()`
- If `home_assistant.enabled: true` in config, publish HA discovery on startup
  and mirror state to `homelab/lighting/{device_id}/state` on every change

### HA discovery payload (conditional)
Publish to `{discovery_prefix}/light/{device_id}/config` on startup:
```json
{
  "name": "<device name from config>",
  "unique_id": "<device_id>",
  "state_topic": "homelab/lighting/{device_id}/state",
  "command_topic": "homelab/lighting/{device_id}/set",
  "payload_on": "ON",
  "payload_off": "OFF"
}
```

---

## Step 5 — HTTP collector

Create `projects/lighting-control/collector/http_collector.py`.

Polling fallback — supplements MQTT for initial state and missed events.

### Gen1 HTTP
```
GET http://{ip}/relay/0     → {"ison": bool, "has_timer": false, ...}
GET http://{ip}/status      → full status JSON with emeter sub-object
```

### Gen2 HTTP RPC
```
POST http://{ip}/rpc/Switch.GetStatus  body: {"id": 0}
     → {"output": bool, "apower": float, "aenergy": {"total": float}}
POST http://{ip}/rpc/Switch.Set        body: {"id": 0, "on": bool}
     → {"was_on": bool}
POST http://{ip}/rpc/Light.Set         body: {"id": 0, "on": bool, "brightness": int}
     → {"was_on": bool}  (dimmable devices only)
```

### Requirements
- Poll all configured devices at `http_poll_interval` seconds (from config)
- Per-device retry with exponential backoff: max 3 attempts, base 1s, cap 4s
- Dispatch Gen1 vs Gen2 based on device `generation` field from config
- Write `lighting_state` with `source=http` tag via writer.py
- Define `DeviceUnreachable(device_id)` custom exception
- Raise `DeviceUnreachable` after all retries exhausted — log warning, continue
- Return `dict[str, dict]` mapping `device_id` → state dict per poll cycle
- Thread-safe — runs alongside MQTT collector
- Structured logging via `shared/` only — no `print()`

---

## Step 6 — Writer

Create `projects/lighting-control/collector/writer.py`.

Thin wrapper around `shared/db/influx.py`. Three functions:

```python
def write_state(client, device_id: str, room: str, device_type: str,
                generation: str, source: str, state: dict) -> None:
    # Writes to lighting_state measurement.
    # state keys: is_on, brightness_pct, power_w, energy_wh, temperature_c, rssi
    # Omit keys where value is None — never write None as a field value.

def write_event(client, device_id: str, room: str, event_type: str,
                triggered_by: str, brightness_pct: float = None) -> None:
    # Writes to lighting_events measurement.

def write_energy(client, device_id: str, room: str,
                 power_w: float, wh_delta: float, wh_total: float) -> None:
    # Writes to lighting_energy measurement.
```

All raise `ValueError` with descriptive message on invalid input (empty device_id,
negative power_w, unknown event_type, etc.).

---

## Step 7 — Flask API routes

Create `projects/lighting-control/dashboard/app.py`.

Follow `projects/solar-battery/dashboard/app.py` patterns exactly.
Run on port 5005.

```
GET /api/lighting/overview
    Returns: {devices_total, devices_on, rooms_total, rooms_with_lights_on,
              total_power_w, data_available}
    No data → 200, data_available: false, numeric fields null.

GET /api/lighting/devices
    Returns: [{device_id, name, room, device_type, generation, is_on,
               brightness_pct, power_w, last_seen, online}]
    online: true when last lighting_state record < 5 min ago.
    Empty list when no data — not an error.

GET /api/lighting/devices/<device_id>
    Single device. Same shape as above.
    Unknown device_id → 404 + {"error": "device not found"}

POST /api/lighting/devices/<device_id>/set
    Body: {"on": bool} or {"brightness": 0–100}
    Publishes MQTT command to correct Gen1 or Gen2 topic.
    Writes lighting_events with triggered_by="api".
    Unknown device_id → 404
    Invalid body → 400
    MQTT unavailable → 503

GET /api/lighting/rooms
    Returns: [{room_id, name, devices_total, devices_on, total_power_w}]

GET /api/lighting/history
    Params: device_id (required), hours (default 24, max 168)
    Returns: [{time, is_on, power_w, brightness_pct}]
    Unknown device_id → 404
    Invalid hours (≤0 or >168 or non-integer) → 400

GET /api/lighting/status
    Returns: {mqtt_connected, influxdb_ok, device_count,
              data_available, last_event_minutes_ago}
```

Exception handling — follow solar-battery pattern exactly:
```python
except ValueError as exc:
    app.logger.warning("Bad request: %s", exc)
    return jsonify({"error": "invalid input"}), 400
except Exception as exc:
    app.logger.error("Service error: %s", exc, exc_info=True)
    return jsonify({"error": "service unavailable"}), 503
```

Never put `str(exc)` or `{exc}` inside any `jsonify()` call.

---

## Step 8 — Dashboard template

Create `projects/lighting-control/dashboard/templates/index.html`.

React + Babel via CDN. Fetch from `/api/lighting/*`. Refresh every 30s.

Six tabs — Phase 1 renders Overview and Devices as functional screens.
The other four show a "Coming in Phase 2" placeholder (calm info message, not an error).

**Overview tab**
- Summary strip: devices on/total, total power (W), rooms count
- Per-room tile grid: room name, lights on/total, power (W)

**Devices tab**
- Table: name, room, on/off indicator, power (W), brightness (if applicable), last seen

**Rooms tab** — placeholder: "Rooms view coming in Phase 2"

**Scenes tab** — placeholder: "Scenes coming in Phase 2"

**Schedules tab** — placeholder: "Schedules coming in Phase 2"

**Presence tab** — placeholder: "Presence detection coming in Phase 2"

Placeholder state when `data_available` is false:
- Show "—" for all numeric values, not 0
- Info banner: "No device data yet — start the collector to populate"
- All six tabs visible and navigable

---

## Step 9 — Dev server

Create `projects/lighting-control/tests/dev_server.py`.

Add this comment block at the top:
```python
# dev_server.py — Lighting control UI development server
# Serves /api/lighting/* routes from pre-generated fixture files.
# Use for UI testing without InfluxDB or Shelly hardware.
#
# Run:  cd projects/lighting-control && python -m tests.dev_server
# Open: http://localhost:5005
#
# Switch UI states via the scenario endpoint:
#   GET /api/lighting/scenario?name=all_on
#   GET /api/lighting/scenario?name=all_off
#   GET /api/lighting/scenario?name=partial
#   GET /api/lighting/scenario?name=no_data
# Refresh the browser after each to see the state change.
#
# NOT for production use. Not covered by the test suite.
```

Load fixture files (`tests/fixtures/`) on startup into memory.
Generate them inline on first run if they do not exist.

Scenario presets:
```python
SCENARIOS = {
    "all_on":  {"devices_on": 4, "devices_total": 4, "total_power_w": 180.0,
                "data_available": True},
    "all_off": {"devices_on": 0, "devices_total": 4, "total_power_w": 0.0,
                "data_available": True},
    "partial": {"devices_on": 2, "devices_total": 4, "total_power_w": 75.0,
                "data_available": True},
    "no_data": {"devices_on": None, "devices_total": 0, "total_power_w": None,
                "data_available": False},
}
```

Serve all `/api/lighting/*` routes with identical JSON shapes to the real app.
Serve the real dashboard template at `/`.
Run on port 5005.
Unknown scenario name → 400 + `{"error": "unknown scenario", "available": [...]}`

---

## Step 10 — Tests

| File | Minimum | Focus |
|---|---|---|
| `test_collector.py` | 40 | Mock paho, requests, shared.db.influx |
| `test_app.py` | 45 | Flask test client, mock InfluxDB, mock MQTT |

**Total target: 85+**

### test_collector.py required coverage
- MQTT connect success and failure
- Gen1 relay/0 scalar topic parse → is_on correct
- Gen1 light/0 JSON topic parse → is_on + brightness_pct
- Gen1 emeter/0/power topic parse → power_w written
- Gen1 emeter/0/energy topic parse → energy_wh written
- Gen2 switch:0 JSON topic parse → is_on + power_w + energy_wh
- Gen2 light:0 JSON topic parse → is_on + brightness_pct
- Unknown topic: logged, skipped, no crash
- shelly_id maps to correct device_id via config
- InfluxDB write success path
- InfluxDB write failure → buffer
- Buffer drain on reconnect
- Buffer overflow (>200) → oldest dropped, warning logged
- HTTP collector Gen1 poll → correct state dict
- HTTP collector Gen2 poll → correct state dict returned
- HTTP collector timeout → DeviceUnreachable raised after 3 retries
- DeviceUnreachable caught at call site → warning logged, loop continues
- Exponential backoff between HTTP retry attempts
- SIGTERM graceful shutdown
- SIGINT graceful shutdown

### test_app.py required coverage

Per route: happy path, no data → correct fallback, InfluxDB → 503.

`/api/lighting/overview`: data_available true, false, all numeric fields
`/api/lighting/devices`: list shape, online flag (< 5 min = true, stale = false), empty
`/api/lighting/devices/<id>`: known device happy path, unknown device → 404
`/api/lighting/devices/<id>/set`: on, off, brightness valid, brightness=101 → 400,
  missing body → 400, unknown device → 404, MQTT unavailable → 503
`/api/lighting/rooms`: list shape, empty list
`/api/lighting/history`: default 24h, custom hours=48, hours=0 → 400,
  hours=169 → 400, hours=abc → 400, unknown device_id → 404, InfluxDB → 503
`/api/lighting/status`: mqtt connected, mqtt disconnected, no InfluxDB data

---

## Step 11 — Verification

```bash
python -m py_compile projects/lighting-control/collector/mqtt_collector.py
python -m py_compile projects/lighting-control/collector/http_collector.py
python -m py_compile projects/lighting-control/collector/writer.py
python -m py_compile projects/lighting-control/dashboard/app.py
python -m py_compile projects/lighting-control/tests/dev_server.py

.venv/bin/python -m pytest projects/lighting-control/tests/ -v --tb=short

.venv/bin/python -m pytest projects/solar-battery/tests/ -v --tb=short
.venv/bin/python -m pytest projects/power-dashboard/tests/ -v --tb=short
.venv/bin/python -m pytest projects/water-monitor/tests/ -v --tb=short
```

Dev server smoke test (timeout is expected):
```bash
cd projects/lighting-control
timeout 5 .venv/bin/python -m tests.dev_server || true
```

Targets:
- lighting-control: **85+ tests passing**
- solar-battery: 122 passing — no regression
- power-dashboard: 160 passing — no regression
- water-monitor: 124 passing — no regression

Also verify:
```bash
grep -n "str(exc)\|{exc}" projects/lighting-control/dashboard/app.py
```
Must return zero matches inside jsonify() calls.

---

## Constraints

- All topic patterns derived from `shelly_id` in `lighting.yaml` — never hardcoded in Python
- Gen1/Gen2 dispatch based on `generation` field from config only — no topic heuristics
- HA discovery and state mirroring: conditional on `home_assistant.enabled: true`
- InfluxDB tags always use `device_id`, never `shelly_id`
- Null fields (brightness_pct, power_w, etc.) must be **omitted** from InfluxDB writes, not written as None or 0
- Structured logging via `shared/` only — no `print()` anywhere
- No `str(exc)` or `{exc}` inside any `jsonify()` call
- No hardcoded IPs, Shelly IDs, or credentials in Python source
- `dev_server.py` is never imported by production code
- All four existing test suites must remain green

---

## Completion summary

Provide:
1. Files created with line counts
2. Test count: test_collector.py / test_app.py / total
3. Confirm HA discovery only runs when `home_assistant.enabled: true`
4. Any Gen1/Gen2 payload assumptions made
5. Confirm dev_server.py starts without import errors
6. Any InfluxDB tag cardinality concerns
7. Suggested Phase 2 branch name

Then update `AGENTS.md` per the session close instructions in `instructions.md` and commit.
