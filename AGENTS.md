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
shared/
  db/influx.py         InfluxDB 2.7 wrapper
  mqtt/client.py       Mosquitto MQTT helper
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

| Project         | Port |
|-----------------|------|
| dns-monitor     | 5000 |
| power-dashboard | 5001 |
| water-monitor   | 5002 |
| solar-battery   | 5003 |
| Grafana         | 3000 |

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

## Testing standards

- Minimum 100 tests per project (water-monitor is the reference at 124).
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
| `main` | Clean — PR #2 merged (water-monitor Phase 2, 124 tests) |
| `feature/power-dashboard-collector` | Power dashboard collector/calculator implementation complete; pending PR |

## Active roadmap

### Power dashboard (current focus)
- [x] MQTT collector for Shelly Pro 3EM + IotaWatt (`collector/mqtt_collector.py`)
- [x] Tiered rate calculator (`dashboard/calculator.py`)
- [x] Calculator API routes (`/api/calculator/*`)
- [x] Test suite to 100+ tests

### Solar/battery dashboard (next)
- [ ] Victron Cerbo GX MQTT subscriber
- [ ] Cerbo keep-alive publisher (60s interval, `R/{portal_id}/keepalive`)
- [ ] Solar data wired into power dashboard net consumption

### Water monitor (stabilized — Phase 2 complete)
- No active work planned.

## Known issues

- **Water monitor Python 3.9 annotation failure is pre-existing on baseline.**
  On `feature/power-dashboard-collector` with all session work stashed,
  `.venv/bin/python -m pytest projects/water-monitor/tests/ -v --tb=short`
  fails during collection because `projects/water-monitor/collector/calculator.py`
  uses `float | None` without `from __future__ import annotations` under
  Python 3.9.6. The literal `python -m pytest ...` command cannot run in this
  shell because `python` is not on `PATH`. Do not patch this on the power
  dashboard branch; fix it separately on `main` before the next session.
