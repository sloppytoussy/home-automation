# Lighting control — Phase 1: foundation and device management

**Branch:** `feature/lighting-phase1`
**Dev server port:** 5005
**Prerequisite:** Run `session-open.md` before starting.

---

## Situation

This is the newest sub-project in the home automation platform, built from
scratch. Phase 1 delivers: project scaffold, Shelly device collection over
MQTT and HTTP, InfluxDB state tracking, a Flask device management API, and
a 6-tab dashboard (Overview and Devices functional; Rooms, Scenes, Schedules,
Presence as Phase 2 placeholders).

Hardware: Shelly Gen1 and Gen2 switches and dimmers. Local-first — the
Mosquitto MQTT broker is already running in the shared Docker stack. No
Shelly cloud account required or used.

---

## Architecture decisions to enforce

### Two collection paths, one state store

Shelly devices publish MQTT state topics on every change. This is the primary
collection path — real-time, low latency. The HTTP poller is a fallback: it
recovers initial state at collector startup and catches any events missed
during a broker restart.

Both paths write to the same `lighting_state` InfluxDB measurement,
distinguished by the `source` tag (`mqtt` vs `http`). The Flask API and
dashboard query InfluxDB only — they never call Shelly HTTP directly.

### Gen1/Gen2 dispatch is config-driven, never heuristic

Shelly generations differ significantly: Gen1 uses scalar MQTT payloads and
`/relay/0` HTTP; Gen2 uses JSON status topics and RPC-over-HTTP. The
`generation: gen1|gen2` field in `lighting.yaml` is the only dispatch signal.
No `if "shellies" in topic` heuristics in Python — adding a new device must
never require code changes.

### device_id is the stable identity, shelly_id is transport-only

`shelly_id` (e.g., `shellyplus1pm-AABBCC`) is the hardware address used for
MQTT topic subscription matching and HTTP targeting. It never appears in
InfluxDB. All tags, API responses, and internal references use `device_id`
(human-readable, stable, defined in config). This keeps tag cardinality low
and InfluxDB queries readable.

### Null fields must be omitted from InfluxDB writes, not zeroed

Non-dimmable devices have no `brightness_pct`. Non-PM devices have no
`power_w` or `energy_wh`. These fields must be absent from the InfluxDB
write call — do not write `None`, `null`, or `0.0` as a substitute. Writing
a zero energy value for a device with no power meter would produce misleading
dashboard data.

### HA-compatible output is gated behind a config flag

When `home_assistant.enabled: true` in `lighting.yaml`, the MQTT collector
publishes HA MQTT discovery payloads on startup and mirrors state updates
to `homelab/lighting/{device_id}/state`. When disabled (the default), zero
HA code runs. The dashboard and all tests work identically either way. HA
integration must never be a prerequisite for anything.

---

## Reference files to read before writing code

1. `projects/power-dashboard/collector/mqtt_collector.py` — threading model,
   buffer pattern, SIGTERM/SIGINT handler to replicate exactly
2. `projects/water-monitor/collector/mqtt_collector.py` — additional pattern
   reference for topic dispatch and InfluxDB write flow
3. `projects/solar-battery/dashboard/app.py` — Flask route patterns, safe
   query helpers, and exception handling template to follow exactly
4. `shared/db/influx.py` — the InfluxDB wrapper; use it for all writes and queries
5. `shared/mqtt/client.py` — MQTT client helper

---

## Shelly payload reference

### Gen1 MQTT
| Topic | Payload |
|---|---|
| `shellies/{shelly_id}/relay/0` | scalar string `"on"` or `"off"` |
| `shellies/{shelly_id}/light/0` | JSON `{"ison": true, "brightness": 75}` |
| `shellies/{shelly_id}/emeter/0/power` | scalar float e.g. `"245.6"` |
| `shellies/{shelly_id}/emeter/0/energy` | scalar float Wh cumulative |

### Gen2 MQTT
| Topic | Payload |
|---|---|
| `{shelly_id}/status/switch:0` | JSON `{"output": true, "apower": 245.6, "aenergy": {"total": 18432.0}}` |
| `{shelly_id}/status/light:0` | JSON `{"output": true, "brightness": 75.0}` |
| `{shelly_id}/events/rpc` | JSON RPC NotifyStatus (mirrors status topics) |

### Gen1 HTTP
| Endpoint | Response |
|---|---|
| `GET http://{ip}/relay/0` | `{"ison": true, "has_timer": false, ...}` |
| `GET http://{ip}/status` | Full status JSON with emeter sub-object |

### Gen2 HTTP RPC
| Endpoint | Body / Response |
|---|---|
| `POST http://{ip}/rpc/Switch.GetStatus` | body `{"id": 0}` → `{"output": true, "apower": 245.6, ...}` |
| `POST http://{ip}/rpc/Switch.Set` | body `{"id": 0, "on": true}` → `{"was_on": false}` |
| `POST http://{ip}/rpc/Light.Set` | body `{"id": 0, "on": true, "brightness": 75}` (dimmable only) |

---

## Flask API — response shapes and error contracts

All routes follow the solar-battery exception handling pattern. Do not deviate.

```python
except ValueError as exc:
    app.logger.warning("Bad request: %s", exc)
    return jsonify({"error": "invalid input"}), 400

except Exception as exc:
    app.logger.error("Service error: %s", exc, exc_info=True)
    return jsonify({"error": "service unavailable"}), 503
```

Never put `str(exc)` or `{exc}` inside `jsonify()`. Verify before finalising:
```bash
grep -n "str(exc)\|{exc}" projects/lighting-control/dashboard/app.py
```
Must return zero matches inside jsonify() calls.

Route-specific notes:
- `GET /api/lighting/devices` — `online: true` when last `lighting_state`
  record is < 5 minutes ago. Stale or missing → `online: false`.
- `POST /api/lighting/devices/<id>/set` — publishes the correct MQTT command
  topic for the device's generation. Also writes a `lighting_events` record
  with `triggered_by="api"`.
- `GET /api/lighting/history` — `hours` must be a positive integer ≤ 168.
  Return 400 for `hours=0`, `hours=-1`, non-integer, or `hours > 168`.
- All "no data" states return HTTP 200 with `data_available: false` and
  numeric fields as `null` — they are not errors.

---

## Dashboard — 6 tabs, 2 active in Phase 1

The UX plan has 6 tabs: Overview, Rooms, Scenes, Schedules, Presence, Devices.
Phase 1 renders Overview and Devices as functional screens. The other four
must be present in the navigation and render a calm informational placeholder:
"[Tab name] coming in Phase 2" — not a spinner, not an error state.

Placeholder state when `data_available` is false (no InfluxDB data):
- Show "—" for all numeric values, not 0 or "null"
- Info banner: "No device data yet — start the collector to populate"
- All six tabs navigable

Match the React + Babel CDN versions used in `projects/solar-battery/dashboard/templates/index.html`.
Auto-fetch every 30 seconds.

---

## Dev server

`tests/dev_server.py` is a standalone Flask app for testing the UI without
InfluxDB or Shelly hardware. Reads fixture files from `tests/fixtures/`,
serves identical JSON shapes to the real API, and adds a scenario endpoint
for switching between preset states. Runs on port 5005.

Scenario endpoint: `GET /api/lighting/scenario?name=<name>`
Scenarios: `all_on`, `all_off`, `partial`, `no_data`
Unknown name → 400 + `{"error": "unknown scenario", "available": [...]}`

This file is never imported by production code and is not covered by the test suite.

---

## Test targets

| Suite | Target |
|---|---|
| `test_collector.py` | 40+ |
| `test_app.py` | 45+ |
| **Total** | **85+** |

### Key collector test cases to verify
- Gen1 and Gen2 MQTT topic parsing produces correct `is_on`, `brightness_pct`,
  `power_w`, `energy_wh` field values
- `shelly_id` topics map to the correct `device_id` via config lookup
- Null-field omission: non-dimmable device write contains no `brightness_pct`
- Buffer fills to 200 then drops oldest on overflow (warning logged)
- `DeviceUnreachable` is caught at the call site — loop continues to next device
- Exponential backoff fires between HTTP retry attempts

### Key app test cases to verify
- `online` flag: last record 4 min ago → true; last record 6 min ago → false
- `POST /set` with `brightness: 101` → 400; with `brightness: 100` → 200
- `GET /history` with `hours=169` → 400
- HA-related code does not execute when `home_assistant.enabled: false`

All four existing test suites must remain green:

| Suite | Expected count |
|---|---|
| water-monitor | 124 |
| power-dashboard | 160 |
| solar-battery | 122 |

---

## Constraints

- `lighting.yaml` is the single source of truth for device topology
- Gen1/Gen2 dispatch is config-driven only — no topic-string heuristics
- HA integration gated on `home_assistant.enabled` — never active by default
- `device_id` (not `shelly_id`) in all InfluxDB tags and API responses
- Null fields omitted from InfluxDB writes — never written as None or 0
- Structured logging via `shared/` only — no `print()` anywhere
- No `str(exc)` inside `jsonify()`
- No hardcoded IPs, Shelly IDs, or credentials in Python source
- `dev_server.py` is a dev tool only — never imported by production code

---

## How to test the UI after the session

```bash
# Start the dev server
cd projects/lighting-control
python -m tests.dev_server

# Open the dashboard
open http://localhost:5005

# Switch UI states and refresh the browser
curl "http://localhost:5005/api/lighting/scenario?name=all_on"
curl "http://localhost:5005/api/lighting/scenario?name=partial"
curl "http://localhost:5005/api/lighting/scenario?name=no_data"
curl "http://localhost:5005/api/lighting/scenario?name=all_off"
```

---

## Completion summary

Provide:
1. All files created with line counts
2. Test count: test_collector.py / test_app.py / total
3. Confirm HA discovery only runs when `home_assistant.enabled: true`
4. Any Gen1/Gen2 payload assumptions made
5. Confirm dev_server.py starts without import errors
6. Any InfluxDB tag cardinality concerns
7. Suggested Phase 2 branch name

Then run `session-close.md`.
