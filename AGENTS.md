# AGENTS.md

## Project overview

Distributed, containerized home automation monitoring system. Local-first
execution — no cloud dependencies. Aggregates data from heterogeneous IoT
devices into real-time dashboards with intelligent alerting.

```
projects/
  power-dashboard/     Flask + InfluxDB · prepaid meter · circuit monitoring
  water-monitor/       Flask + InfluxDB · dual underground tanks · Phase 2 complete
  solar-battery/       Flask + InfluxDB · Victron integration (planned)
  dns-monitor/         Flask + InfluxDB · Pi-hole v6
  lighting-control/    Flask + InfluxDB · Shelly Gen1/Gen2 · MQTT + HTTP · port 5005
shared/
  db/influx.py         InfluxDB 2.7 wrapper
  mqtt/client.py       Mosquitto MQTT helper
  auth/                Flask auth blueprint + YAML user store
  utils/               Structured logging
infrastructure/
  docker/
  grafana/
  influxdb/
  nginx/
```

## Project commands

```bash
# Install (per project)
cd projects/<project>
pip install -r requirements.txt --break-system-packages

# Run app (per project)
python -m flask --app dashboard.app run --host 0.0.0.0 --port <port>

# Run tests (per project)
python -m pytest projects/<project>/tests/ -v

# Run all tests
python -m pytest projects/ -v

# Docker (use docker-compose on this machine, not docker compose)
docker-compose up -d
docker-compose logs -f <service>
```

## Port assignments

| Project          | Port |
|------------------|------|
| dns-monitor      | 5000 |
| power-dashboard  | 5001 |
| water-monitor    | 5002 |
| solar-battery    | 5003 |
| water-monitor dev| 5004 |
| lighting-control | 5005 |
| Grafana          | 3000 |

## Environment variables (names only)

```
INFLUXDB_URL
INFLUXDB_TOKEN
INFLUXDB_ORG
INFLUXDB_BUCKET
MQTT_BROKER_HOST
MQTT_BROKER_PORT
SMTP_HOST
SMTP_PORT
SMTP_USER
SMTP_PASSWORD
ALERT_EMAIL_TO
SECRET_KEY
AUTH_USERS_FILE
AUTH_SESSION_LIFETIME_HOURS
```

## Runtime notes

- Python 3.9.6 on this machine (use `from __future__ import annotations` for
  union type hints)
- Virtual environment: `.venv/` at repo root
- `docker compose` is not available — use `docker-compose` (hyphenated)
- Flask templates use React + Babel via CDN (no build step)
- InfluxDB env vars accessed via `os.getenv()` with safe fallbacks, never
  `os.environ[]` directly (causes crashes when Influx is unconfigured)
- Jinja templates wrapping JSX must use `{% raw %}...{% endraw %}` blocks

## Hardware context

| Device | Role | Protocol |
|---|---|---|
| Landis+Gyr JH145 | Utility meter — ground truth only | Manual entry |
| Shelly Pro 3EM | Mains totals — 3-phase | MQTT native |
| IotaWatt | Circuit-level — 14 CT inputs | REST local + optional MQTT |
| Dayliff DDA 1000P | Water pump (×2) | Monitored via Tuya/MQTT |
| Victron Cerbo GX | Solar + battery aggregator | MQTT (planned) |
| Pi-hole v6 | DNS filtering | REST API |
| Shelly Gen1 (shelly1, shelly1pm, shellydimmer2) | Room lighting | MQTT + HTTP local |
| Shelly Gen2 (shellyplus1pm, shellyplus1) | Room lighting | MQTT + HTTP RPC local |

## Architecture decisions

- **Manual entry is not deprecated.** The Landis+Gyr meter is utility-owned.
  Manual readings are the authoritative verification layer for automated totals.
- **Device-agnostic collectors.** Shelly and IotaWatt differ only in YAML
  config, not in collector code. Topic patterns and field maps live in
  `config/power_collector.yaml`.
- **Shared libraries are mandatory.** Never duplicate InfluxDB, MQTT, or
  logging logic across projects. Use `shared/`.
- **Exponential backoff on all network-dependent services.** Max 5 retries,
  base delay 2s, cap 60s. See `water-monitor/collector/notifier.py` for the
  reference implementation.
- **Solar export fields exist now.** `solar_export_kwh` defaults to `0.0` in
  the power dashboard schema. Victron/Cerbo will populate it when the solar
  session runs. Do not remove these fields.
- **RWF tiered tariff.** REG (Rwanda) residential prepaid rate structure:
  0–20 kWh at 89 RWF/kWh, 21–50 kWh at 310 RWF/kWh, 51+ kWh at 369 RWF/kWh.
- **Lighting: device_id not shelly_id.** `shelly_id` (hardware address) is used
  for MQTT topic matching and HTTP targeting only. All InfluxDB tags and API
  responses use `device_id` (stable, human-readable, from config).
- **Lighting: Gen1/Gen2 dispatch is config-driven.** The `generation: gen1|gen2`
  field in `lighting.yaml` is the only dispatch signal. No topic-string heuristics.
- **Lighting: null fields omitted from writes.** `_clean_fields()` in
  `lighting-control/collector/writer.py` strips None values before every InfluxDB
  write. Non-dimmable and non-PM devices never write zero-valued placeholders.
- **Lighting: HA discovery is opt-in.** `home_assistant.enabled: false` by default.
  When true, discovery payloads publish to `homeassistant/light/{device_id}/config`
  and state mirrors to `homelab/lighting/{device_id}/state`.
- **Auth is shared only.** Dashboard authentication lives in `shared/auth/` as a
  Flask Blueprint backed by `infrastructure/users.yaml`; dashboards register the
  blueprint and decorators without duplicating auth logic.
- **Auth users file is private.** `infrastructure/users.yaml` contains bcrypt
  password hashes and is gitignored; commit only `infrastructure/users.yaml.example`.

## Testing standards

- Minimum 100 tests per project (water-monitor: 170, lighting-control: 96).
- All hardware and network dependencies must be mocked. No real Modbus, MQTT,
  Tuya, or InfluxDB calls in tests.
- Mock targets: `paho.mqtt.client.Client`, `pymodbus.client.ModbusTcpClient`,
  `requests`, `shared.db.influx`, `smtplib.SMTP`.
- Tests must pass CodeQL and Python analysis before any PR is promoted
  to ready-for-review.
- DNS monitor has a known pre-existing test failure (`requests_mock` fixture
  missing) — do not chase this unless explicitly requested.

## Code patterns to follow

- **Reference for MQTT + threading:** `projects/water-monitor/collector/mqtt_collector.py`
- **Reference for Modbus polling:** `projects/solar-battery/collector/modbus_collector.py`
- **Reference for alerting + backoff:** `projects/water-monitor/collector/notifier.py`
- **Reference for config validation:** `projects/water-monitor/collector/config_validator.py`
- **Reference for test mock patterns:** `projects/water-monitor/tests/test_alerter.py`
- **Reference for Shelly Gen1/Gen2 MQTT + HTTP:** `projects/lighting-control/collector/mqtt_collector.py`
- **Reference for HA discovery pattern:** `projects/lighting-control/collector/mqtt_collector.py`

## Rules

- Never use `print()` — use structured logging via `shared/utils/`.
- Never hardcode IPs, ports, credentials, or tariff rates in Python source.
  Everything from config files or environment variables.
- Never use bare `except` clauses — always catch specific exceptions.
- Never use `shell=True` in subprocess calls.
- Never add Claude, Codex, ChatGPT, Anthropic, OpenAI, or any AI tool as
  a co-author in commits. Commits must show only the human author.
- Do not rewrite files outside the stated scope of a task.
- Do not modify existing manual entry routes in `dashboard/app.py`.
- Run the relevant tests before finalizing any change.
- `package-lock.json` in the repo root is accidental — do not commit it.

## Current branch state (as of last session)

| Branch | Status |
|---|---|
| `main` | Cleanup complete — water-monitor Python 3.9 annotations fixed; CodeQL #1–7 resolved |
| `feature/power-dashboard-collector` | Merged — power dashboard collector/calculator/test suite complete |
| `feature/solar-battery-phase1-dashboard` | Solar dashboard UI/API/query schema complete; tests at 122 passing |
| `feature/lighting-phase1` | Lighting foundation complete — Shelly Gen1/Gen2 MQTT+HTTP, Flask API, 6-tab dashboard, 96 tests passing |
| `feature/auth-foundation` | Shared auth foundation complete — Blueprint, YAML user store, bcrypt helper, lighting-control proof-of-concept |

## Active roadmap

### Completed
- [x] Auth foundation: shared Flask Blueprint, bcrypt-backed YAML user store,
  login/logout/me routes, and lighting-control index-route integration

### Lighting control
- [x] Phase 1: scaffold, Shelly Gen1/Gen2 MQTT + HTTP collectors, Flask API, 6-tab dashboard
- [x] Dev server: `cd projects/lighting-control && ../.venv/bin/python -m tests.dev_server` (port 5005)
- [ ] Phase 2: Rooms (zone/group hierarchy, bulk control), Scenes (composer, pip row preview)
- [ ] Phase 2: Schedules (cron + sunrise/sunset triggers, Kigali lat/long pre-filled)
- [ ] Phase 2: Presence (Home/Away/Sleep modes, MQTT topic for external triggers)
- [ ] Phase 2 branch: `feature/lighting-phase2`

### Power dashboard (current focus)
- [x] MQTT collector for Shelly Pro 3EM + IotaWatt (`collector/mqtt_collector.py`)
- [x] Tiered rate calculator (`dashboard/calculator.py`)
- [x] Calculator API routes (`/api/calculator/*`)
- [x] Test suite to 100+ tests

### Solar/battery dashboard
- [x] Phase 1 dashboard UI with placeholder Cerbo GX state
- [x] `/api/solar/*` Flask routes and InfluxDB query layer
- [x] `solar_readings` schema documentation and collector config stub
- [x] Fixture-backed dev server:
  `cd projects/solar-battery && python -m tests.dev_server`
- [ ] Phase 2 Victron Cerbo GX MQTT subscriber — blocked until Cerbo GX
  hardware is purchased
- [ ] Phase 2 Cerbo keep-alive publisher (60s interval,
  `R/{portal_id}/keepalive`)
- [ ] Phase 2 solar data wired into power dashboard net consumption

Battery note: solar/battery uses a third-party LifePO4 2x12V 200Ah battery
with integrated BMS. Cerbo telemetry is expected to be pack-level only:
SOC, voltage, current, and power. No cell-level dashboard fields are planned.

### Water monitor (stabilized — Phase 2 complete)
- No active work planned.

## CodeQL status

- Alerts #1–7 resolved on `main`: dashboard JSON error responses no longer
  expose raw exception messages.
