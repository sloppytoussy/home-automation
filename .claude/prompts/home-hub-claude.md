# Home hub — navigation page, service aggregation, auth integration

**Branch:** `feature/home-hub`
**Port:** 5006
**Prerequisite:** Run `session-open.md` before starting.

---

## Situation

The home hub is a new Flask sub-project that serves as the authenticated entry
point to the platform. It aggregates live status and key metrics from all five
sub-projects by calling their existing API endpoints, checks infrastructure
health (InfluxDB, Grafana, MQTT), and renders a single-page dashboard. Auth
from `shared/auth/` (Phase 2) is integrated from the start.

---

## Architecture decisions to enforce

### Hub aggregates — it never duplicates

The hub calls each sub-project's existing endpoint and extracts relevant
fields. It does not replicate InfluxDB queries, does not import any project's
Python modules, and does not add new routes to sub-projects. If a sub-project
doesn't expose a field the hub wants, the hub shows "—", not a workaround.

### Parallel fetches with independent failure handling

All five service fetches must run in parallel via `ThreadPoolExecutor`. A
timeout or error on one service must never delay or break the others. The hub
returns HTTP 200 even when all services are offline — the frontend handles the
empty state. This is critical: a hub that returns 503 when services are down
is useless precisely when you need it most.

### Extract metrics is a pure function — never raises

`extract_metrics(service_id, data)` must handle any input shape without
raising. Missing keys return `None`. Unknown service_id returns `{}` with a
log warning. This function must have full test coverage for each service type
including malformed and empty inputs.

### Auth gates the UI, not the API

`GET /` requires `@require_auth` — unauthenticated browsers get redirected
to `/auth/login?next=/`. The `/api/hub/overview` and `/api/hub/status` routes
are intentionally public so the React frontend can fetch after the page loads
without needing to pass tokens. The frontend is only reachable after login
anyway since the HTML page itself requires auth.

### hub.yaml drives everything

Service URLs, ports, endpoints, and infrastructure addresses all come from
`hub.yaml`. No URL or hostname is hardcoded in Python. Service URLs are
overridable via environment variables for Docker deployments where container
names replace localhost.

---

## Reference files to read before reviewing

1. `projects/lighting-control/dashboard/app.py` — auth integration pattern,
   `.env` loading, config loading
2. `projects/solar-battery/dashboard/app.py` — exception handling, jsonify patterns
3. `shared/auth/__init__.py` — confirm Blueprint name and decorator imports
4. `projects/home-hub/config/hub.yaml` — verify all 5 services and infrastructure

---

## Sub-project endpoint map

The hub calls these existing endpoints — confirm the response shapes are
handled correctly in `extract_metrics`:

| Service | Endpoint | Key fields |
|---|---|---|
| dns_monitor | `/api/summary` | `dns_queries_today`, `ads_percentage_today` |
| power_dashboard | `/api/summary` | `remaining_kwh`, `days_left`, `consumption_rate_kwh_per_day` |
| water_monitor | `/api/tanks` | list of `{id, name, level_pct, volume_liters}` |
| solar_battery | `/api/solar/summary` | `battery_soc_pct`, `pv_power_w`, `data_available` |
| lighting_control | `/api/lighting/overview` | `devices_on`, `devices_total`, `total_power_w` |

Infrastructure:
- InfluxDB: `GET {url}/health` → 200 = online
- Grafana: `GET {url}/api/health` → 200 = online
- MQTT: `socket.connect(host, port, timeout=2)` → no exception = online

---

## Security checklist

```bash
# No str(exc) in jsonify
grep -n "str(exc)\|{exc}" projects/home-hub/dashboard/app.py
# Must return zero matches inside jsonify() calls

# Auth on index route
grep -n "require_auth" projects/home-hub/dashboard/app.py
# Must show @require_auth on the / route

# No hardcoded URLs
grep -n "localhost\|127.0.0.1\|http://" projects/home-hub/dashboard/app.py
# Should only appear in config loading, never as string literals in routes

# PYTHONPATH set
grep "PYTHONPATH" projects/home-hub/Dockerfile
# Must show ENV PYTHONPATH=/app
```

---

## Test cases to spot-check

- `extract_metrics("water_monitor", [])` → `{"tanks": []}`, no raise
- `extract_metrics("solar_battery", {"battery_soc_pct": None})` → `{"battery_soc_pct": None, ...}`
- `extract_metrics("unknown", {"anything": 1})` → `{}`, no raise
- Service fetch with `requests.Timeout` → `online: false`, rest of services unaffected
- Service returns HTTP 500 → `online: false` (online means reachable, not healthy)
- `GET /api/hub/overview` with all mocked services down → HTTP 200, `services_online: 0`
- `GET /` with no session → 302 to `/auth/login?next=/`
- `GET /` with valid session → 200

---

## Dashboard layout to verify

Open `http://localhost:5006` after starting the dev server and check:

1. Header shows "Home Automation" · "Kigali · Home Automation" · status pills · live badge · username + logout
2. Five service cards in a responsive grid — each with name, metrics, online badge, port, Open link
3. Infrastructure row — InfluxDB, Mosquitto, Grafana chips with status dots
4. Card with `online=false` shows "—" metrics and muted styling
5. Card with `data_available=false` but `online=true` shows "—" and amber "Waiting" badge
6. Dev server scenarios work: `all_online`, `some_offline`, `no_data`

---

## Test targets

| Suite | Target |
|---|---|
| `test_app.py` | 45+ |

Existing suites must remain green:

| Suite | Expected |
|---|---|
| water-monitor | 170 |
| power-dashboard | 160 |
| solar-battery | 122 |
| lighting-control | 96 |
| shared/auth | 73 |

---

## Constraints

- `hub.yaml` drives all service URLs and ports — nothing hardcoded in Python
- Parallel fetches — `ThreadPoolExecutor`, independent failure handling
- `extract_metrics` never raises on any input
- `GET /` requires `@require_auth` — `GET /api/hub/*` is public
- `PYTHONPATH=/app` in Dockerfile
- No `print()` — use `app.logger`
- No `str(exc)` inside `jsonify()`
- No bare `except` clauses

---

## How to test after the session

```bash
# Start dev server
cd projects/home-hub
../../.venv/bin/python -m tests.dev_server

# Open hub
open http://localhost:5006    # should redirect to /auth/login
# Log in with credentials from infrastructure/users.yaml
# Hub loads with fixture data

# Test scenarios
curl "http://localhost:5006/api/hub/scenario?name=some_offline"
curl "http://localhost:5006/api/hub/scenario?name=no_data"
```

---

## Completion summary

Provide:
1. All files created or modified with line counts
2. Test count: test_app.py total
3. Confirm auth Blueprint registered, `/` redirects unauthenticated
4. Confirm dev server starts without import errors
5. Confirm PYTHONPATH=/app in Dockerfile
6. Any sub-project endpoint shape assumptions
7. Phase 3 branch name: `feature/dashboard-guards`

Then run `session-close.md`.
