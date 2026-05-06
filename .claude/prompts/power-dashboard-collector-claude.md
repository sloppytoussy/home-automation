# Power dashboard — MQTT collector + calculator

**Branch:** `feature/power-dashboard-collector`
**Prerequisite:** Run `session-open.md` before starting.

---

## Context

The power dashboard has two data entry paths that must coexist:

1. **Manual entry (Flask form)** — authoritative verification layer. Do not
   modify or remove any existing manual entry routes.
2. **Automated MQTT collection** — Shelly Pro 3EM (mains totals) and IotaWatt
   (circuit-level). Both are MQTT-native and local-first.

The Landis+Gyr JH145 utility meter is not a direct data source. Manual
readings from it serve as ground-truth verification against automated totals.

Solar/Victron integration is a future phase. Design the schema and calculator
to accept a `solar_export_kwh` field that defaults to `0.0` for now.

---

## Step 1 — Read these files first

Before writing any code, read:

1. `projects/water-monitor/collector/mqtt_collector.py`
2. `projects/power-dashboard/dashboard/app.py`
3. `projects/power-dashboard/collector/writer.py`
4. `shared/` — identify the InfluxDB wrapper and MQTT helper by name

Do not proceed until you have read all four.

---

## Step 2 — Define the InfluxDB schema

Create `projects/power-dashboard/config/schema.md`:

```
power_readings          (per-poll, from MQTT collector)
  tags:    circuit, location, source_device, phase (L1|L2|L3|total)
  fields:  watts, amps, volts, power_factor, frequency (all float)
  time:    nanosecond precision

energy_totals           (daily rollups)
  tags:    source (mqtt|manual|utility_manual)
  fields:  kwh_import, kwh_export (default 0.0), kwh_net, cost_usd,
           solar_export_kwh (default 0.0 — reserved for Victron)
  time:    day-aligned UTC

verification_log        (manual vs automated comparison)
  tags:    source_a, source_b
  fields:  delta_kwh, delta_pct (float), flagged (boolean)
  time:    timestamp of comparison

solar_readings          (STUB ONLY — not populated this session)
  tags:    device, source (victron_cerbo)
  fields:  pv_power_w, battery_soc_pct, grid_power_w, ac_load_w (float)
  time:    nanosecond precision
```

Document tag cardinality decisions and recommended retention policies.

---

## Step 3 — Implement collector/mqtt_collector.py

Device-agnostic MQTT subscriber. Pattern directly on
`water-monitor/collector/mqtt_collector.py`.

### Shelly Pro 3EM topic structure
```
shellies/{device_id}/emeter/0/power       float watts L1
shellies/{device_id}/emeter/1/power       float watts L2
shellies/{device_id}/emeter/2/power       float watts L3
shellies/{device_id}/emeter/0/energy      float Wh cumulative
shellies/{device_id}/emeter/0/voltage     float volts
shellies/{device_id}/emeter/0/current     float amps
shellies/{device_id}/emeter/0/pf          float power factor
```
Payload: scalar float as UTF-8 string e.g. `"2415.3"`

### IotaWatt topic structure
```
iotawatt/{device_id}/sensor/{name}/value  float watts
iotawatt/{device_id}/sensor/{name}/wh     float Wh cumulative
```
Payload: JSON object `{"value": 2415.3, "units": "Watts"}`

IotaWatt also exposes a local REST API at `/query`. Support both.
REST polling interval: configurable, default 60s.

### Requirements
- Subscribe to configurable topic patterns from YAML only, never hardcoded
- Parse both scalar and JSON payloads (attempt JSON parse, fall back to float)
- Map channel numbers to circuit names via config
- Write to InfluxDB via `shared/` wrapper
- On parse error: log and skip, do not crash
- On InfluxDB write failure: buffer up to 100 readings, retry on reconnect
- On buffer overflow (>100): drop oldest, log warning
- Graceful SIGTERM/SIGINT shutdown
- Structured logging via `shared/` only — no `print()`

### Config: projects/power-dashboard/config/power_collector.yaml
```yaml
mqtt:
  broker_host: localhost
  broker_port: 1883
  topic_patterns:
    - "shellies/+/emeter/#"
    - "iotawatt/+/sensor/#"
devices:
  - id: shelly_main
    type: shelly_3em
    location: main_panel
  - id: iotawatt_circuits
    type: iotawatt
    rest_host: 192.168.1.x
    rest_poll_interval: 60
circuits:
  - device: shelly_main
    channel: "emeter/0"
    name: mains_L1
    phase: L1
  - device: shelly_main
    channel: "emeter/1"
    name: mains_L2
    phase: L2
  - device: shelly_main
    channel: "emeter/2"
    name: mains_L3
    phase: L3
  - device: iotawatt_circuits
    channel: "sensor/hvac"
    name: hvac
    phase: total
  - device: iotawatt_circuits
    channel: "sensor/kitchen"
    name: kitchen
    phase: total
influxdb:
  bucket: power
  org: homelab
collection:
  buffer_size: 100
solar:
  stub: true
  cerbo_portal_id: "REPLACE_WITH_PORTAL_ID"
  cerbo_mqtt_broker: localhost
```

---

## Step 4 — Implement dashboard/calculator.py

Pure Python stdlib only (`math`, `datetime`, `typing`). No Flask, no I/O,
no InfluxDB calls. Fully unit-testable in isolation.

### TieredRate dataclass
```python
@dataclass
class TieredRate:
    tiers: list[dict]   # [{"limit_kwh": 500, "rate": 0.12},
                        #  {"limit_kwh": None, "rate": 0.18}]
    fixed_charges: float
    billing_days: int = 30
```
Tiers evaluated in order. `limit_kwh: None` = final unlimited tier, must
be last. Raise `ValueError` if tiers empty or last tier has a limit.

### Required functions

```
calculate_tiered_cost(kwh_consumed, rate) -> dict
  Returns: {total_cost, energy_cost, fixed_charges, tier_breakdown}
  tier_breakdown: [{tier_index, kwh_in_tier, rate_per_kwh, cost}]
  Raises ValueError if kwh_consumed < 0

calculate_net_consumption(kwh_import, kwh_export=0.0,
                          solar_export_kwh=0.0) -> dict
  Returns: {net_kwh, import_kwh, export_kwh, solar_export_kwh,
            is_net_producer, total_export_kwh}
  Raises ValueError if any value negative

load_breakdown(circuit_readings: list[dict]) -> list[dict]
  Input: [{circuit, watts}]
  Returns: sorted descending by watts, each item adds {pct_of_total}
  pct_of_total values must sum to 100.0 ±0.01
  Raises ValueError if empty or any watts < 0

detect_variance(manual_kwh, automated_kwh, threshold_pct=2.0) -> dict
  Returns: {delta_kwh, delta_pct, flagged, manual_kwh,
            automated_kwh, threshold_pct}
  delta_pct = ((automated - manual) / manual) × 100
  flagged = True when abs(delta_pct) > threshold_pct
  Raises ValueError if manual_kwh <= 0

project_monthly(current_kwh, days_elapsed, rate) -> dict
  Returns: {projected_kwh, projected_cost_breakdown, confidence,
            avg_daily_kwh, days_elapsed, days_remaining}
  confidence: "low" < 5d, "medium" < 15d, "high" >= 15d
  Raises ValueError if days_elapsed <= 0 or current_kwh < 0
```

---

## Step 5 — Integrate calculator into Flask routes

Add to `dashboard/app.py`. Do not modify or remove any existing routes.

```
POST /api/calculator/bill-estimate
     Body: {kwh, tiers: [{limit_kwh, rate}], fixed_charges}
     Returns: calculate_tiered_cost()

GET  /api/calculator/net-consumption
     Params: import_kwh, export_kwh (opt), solar_export_kwh (opt)
     Returns: calculate_net_consumption()

GET  /api/calculator/load-breakdown
     Param: minutes (default 60)
     Queries InfluxDB for circuit power_readings in last N minutes
     Returns: load_breakdown()

GET  /api/calculator/variance
     Queries InfluxDB for latest automated total and latest manual entry
     Returns: detect_variance()

POST /api/calculator/projection
     Body: {tiers, fixed_charges, billing_days (opt)}
     Derives current_kwh and days_elapsed from InfluxDB
     Returns: project_monthly()
```

All routes return:
- HTTP 400 + `{"error": "...", "field": "..."}` on bad input
- HTTP 503 + `{"error": "InfluxDB unavailable"}` on DB failure
- HTTP 200 + calculator result on success

---

## Step 6 — Victron/Cerbo MQTT stub

Create `collector/victron_collector.py` — stub file only, no active
collection. Include this comment block:

```python
# Victron Cerbo GX MQTT Integration — Planned (Solar Session)
#
# Topic schema:
# N/{portal_id}/system/0/Ac/Consumption/L1/Power    (float W)
# N/{portal_id}/system/0/Ac/Consumption/L2/Power    (float W)
# N/{portal_id}/system/0/Ac/Consumption/L3/Power    (float W)
# N/{portal_id}/system/0/Ac/Grid/L1/Power           (float W, +import/-export)
# N/{portal_id}/system/0/Dc/Battery/Soc             (float %, 0-100)
# N/{portal_id}/system/0/Dc/Battery/Power           (float W, +charge/-discharge)
# N/{portal_id}/system/0/Dc/Battery/Voltage         (float V)
# N/{portal_id}/solarcharger/+/Yield/Power          (float W, per MPPT)
# N/{portal_id}/solarcharger/+/History/Daily/0/Yield (float kWh, today)
# N/{portal_id}/solarcharger/+/State               (int: 0=off 2=fault 3=bulk
#                                                        4=absorption 5=float)
# N/{portal_id}/vebus/0/Ac/Out/L1/P                (float W, inverter output)
#
# Payload format: JSON {"value": <float|null>}
# Null = device offline. Handle gracefully — do not crash.
#
# Keep-alive: publish empty payload to R/{portal_id}/keepalive every 60s.
# Cerbo silently stops sending data if keep-alive lapses.
#
# portal_id: found in VRM portal settings. Must be configurable — never hardcode.
#
# InfluxDB target: solar_readings measurement (see schema.md)
#   Tags: device=cerbo, portal_id, source=victron_cerbo
#
# Power dashboard integration:
#   solar_export_kwh in energy_totals populated from solarcharger Daily Yield.
#   calculate_net_consumption() already accepts solar_export_kwh.
#   No calculator changes needed when this collector is implemented.
```

---

## Step 7 — tests/test_calculator.py

Minimum 45 tests. Pure unit tests, no mocking needed.

Required coverage:
- `TieredRate` validation
- `calculate_tiered_cost`: within tier, spanning tiers, zero consumption,
  tier_breakdown sums to kwh_consumed, negative kwh raises
- `calculate_net_consumption`: import only, with export, with solar,
  net producer, all three, negative raises
- `load_breakdown`: single, multi sorted, all equal, zero watts circuit,
  empty raises, negative raises
- `detect_variance`: within/at/above threshold, negative delta, manual=0 raises
- `project_monthly`: each confidence band, correct projection math,
  days_elapsed=0 raises, negative kwh raises

---

## Step 8 — tests/test_collector.py

Minimum 35 tests.

Mock targets: `paho.mqtt.client.Client`, `requests`, `shared.db.influx`

Required coverage:
- MQTT connect success and failure
- Topic subscription matches all config patterns
- Shelly scalar payload parse → correct field values
- IotaWatt JSON payload parse → correct field values
- IotaWatt REST poll → correct parse
- Unknown topic: logged, skipped, no crash
- Circuit name mapping from config
- InfluxDB write success
- InfluxDB write failure → buffer
- Buffer drain on reconnect
- Buffer overflow → oldest dropped, warning logged
- SIGTERM graceful shutdown
- SIGINT graceful shutdown

---

## Step 9 — tests/test_app.py (new routes only)

Minimum 25 tests. Flask test client. Mock InfluxDB and calculator where needed.

Coverage per route: happy path, missing required params → 400,
InfluxDB unavailable → 503, edge case values.

---

## Step 10 — CI validation

```bash
python -m pytest projects/power-dashboard/tests/ -v
```

Target: 105+ tests, all passing.

Final checks:
- No hardcoded credentials or IPs in non-config files
- No bare `except` clauses
- No `print()` calls
- No `shell=True` in subprocess

---

## Constraints

- Manual entry routes in `app.py` must remain fully functional
- `calculator.py` has zero external dependencies (stdlib only)
- Collector is device-agnostic — Shelly and IotaWatt differ in YAML only
- `solar_export_kwh` exists in schema and calculator — do not remove it
- Never break existing water-monitor or dns-monitor tests
- All new code follows water-monitor patterns exactly

---

## Completion summary

Provide:
1. All files created or modified with line counts
2. Test count: calculator / collector / app / total
3. Any assumptions made about Shelly or IotaWatt payload formats
4. Any tag cardinality concerns noted in schema.md
5. Confirmation that `collector/victron_collector.py` stub exists
6. Suggested next branch name for the solar/Victron session

Then run `session-close.md`.
