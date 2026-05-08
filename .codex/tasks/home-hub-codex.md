# Task: home-hub

**Branch:** `feature/home-hub`
**Scope:** `projects/home-hub/` only, plus `docker-compose.yml`

## Allowed files to create or modify

```
projects/home-hub/                                     CREATE (scaffold)
projects/home-hub/dashboard/__init__.py                CREATE
projects/home-hub/dashboard/app.py                     CREATE
projects/home-hub/dashboard/templates/index.html       CREATE
projects/home-hub/config/hub.yaml                      CREATE
projects/home-hub/requirements.txt                     CREATE
projects/home-hub/Dockerfile                           CREATE
projects/home-hub/tests/__init__.py                    CREATE
projects/home-hub/tests/test_app.py                    CREATE
projects/home-hub/tests/dev_server.py                  CREATE
projects/home-hub/tests/fixtures/hub_overview.json     CREATE
docker-compose.yml                                     MODIFY (add home-hub service)
AGENTS.md                                              MODIFY (session close only)
```

Do not touch any file outside this list without explicit permission.

---

## Context

The home hub is the entry point to the entire platform — a single authenticated
page showing all five dashboards at a glance with live status and key metrics,
plus infrastructure health. It runs on port 5006 and aggregates data from each
sub-project's existing API endpoints.

Auth is already on `main` via `shared/auth/`. Register the Blueprint here.
The hub is the first place a user lands after login.

---

## Step 1 — Read first

Before writing any code, read:
- `projects/lighting-control/dashboard/app.py` — Flask patterns, .env loading, auth integration
- `projects/solar-battery/dashboard/app.py` — exception handling patterns
- `shared/auth/__init__.py` — auth Blueprint and decorators
- `projects/lighting-control/Dockerfile` — Dockerfile pattern with PYTHONPATH

---

## Step 2 — Config file

Create `projects/home-hub/config/hub.yaml`:

```yaml
services:
  - id: dns_monitor
    name: "DNS monitor"
    url: "http://localhost:5000"
    metrics_endpoint: "/api/summary"
    port: 5000

  - id: power_dashboard
    name: "Power dashboard"
    url: "http://localhost:5001"
    metrics_endpoint: "/api/summary"
    port: 5001

  - id: water_monitor
    name: "Water monitor"
    url: "http://localhost:5002"
    metrics_endpoint: "/api/tanks"
    port: 5002

  - id: solar_battery
    name: "Solar & battery"
    url: "http://localhost:5003"
    metrics_endpoint: "/api/solar/summary"
    port: 5003

  - id: lighting_control
    name: "Lighting control"
    url: "http://localhost:5005"
    metrics_endpoint: "/api/lighting/overview"
    port: 5005

infrastructure:
  influxdb:
    url: "http://localhost:8086"
    health_path: "/health"
  grafana:
    url: "http://localhost:3000"
    health_path: "/api/health"
  mqtt:
    host: "localhost"
    port: 1883

hub:
  fetch_timeout_seconds: 2
  refresh_interval_seconds: 30
```

In Docker, service URLs resolve by container name. Override via environment
variables `HUB_SERVICE_{ID}_URL` if needed — never hardcode IPs.

---

## Step 3 — Flask app

Create `projects/home-hub/dashboard/app.py`. Run on port 5006.

Follow `projects/lighting-control/dashboard/app.py` patterns exactly for
.env loading, config loading, and exception handling.

### Auth setup
```python
from shared.auth import auth_bp, require_auth
app.secret_key = os.getenv("SECRET_KEY", "dev-key-replace-in-production")
app.register_blueprint(auth_bp)
```

### Key metric extraction

Implement `extract_metrics(service_id: str, data: dict | list) -> dict`:

```
dns_monitor    → {queries_today, blocked_pct}
                 data keys: dns_queries_today, ads_percentage_today
power_dashboard → {remaining_kwh, days_left, consumption_rate_kwh_per_day}
                 data keys: remaining_kwh, days_left, consumption_rate_kwh_per_day
water_monitor  → {tanks: [{id, name, level_pct, volume_liters}]}
                 data is a list — map each tank's level_pct and volume_liters
solar_battery  → {battery_soc_pct, pv_power_w, data_available}
                 data keys: battery_soc_pct, pv_power_w, data_available
lighting_control → {devices_on, devices_total, total_power_w}
                 data keys: devices_on, devices_total, total_power_w
```

Unknown service_id → return empty dict, log warning.
Missing keys → return None for that field, never raise.

### Infrastructure health checks

Implement `check_infrastructure(config: dict) -> dict`:

```python
# InfluxDB: GET {url}/health → online if HTTP 200
# Grafana:  GET {url}/api/health → online if HTTP 200
# MQTT:     socket.connect(host, port, timeout=2) → online if no exception
# All checks: 2s timeout, catch all exceptions, return {online: bool, ...}
```

### Routes

```
GET /
    @require_auth
    Renders index.html. Passes {username, role} from get_session_user() to template.

GET /api/hub/overview
    No auth required — called by the React frontend after login.
    Fetches each service's metrics_endpoint in parallel (use ThreadPoolExecutor,
    max_workers=5, timeout=2s per request).
    Checks infrastructure health.
    Returns:
    {
      services: [
        {id, name, port, url, online, data_available, key_metrics: {},
         last_updated: ISO timestamp or null}
      ],
      infrastructure: {
        influxdb: {online, url},
        grafana:  {online, url},
        mqtt:     {online, host, port}
      },
      services_online: int,
      services_total:  int,
      data_available:  bool,
      last_updated:    ISO timestamp
    }
    online: true if HTTP request returns any response within timeout.
    data_available per service: true if metrics response is non-empty.
    On complete failure: return above shape with all online=false, HTTP 200.

GET /api/hub/status
    No auth required.
    Returns: {online: true, services_total, services_online, last_updated}
    Used by future hubs or health monitors.
```

Exception handling — follow solar-battery pattern exactly:
```python
except ValueError as exc:
    app.logger.warning("Bad request: %s", exc)
    return jsonify({"error": "invalid input"}), 400
except Exception as exc:
    app.logger.error("Hub error: %s", exc, exc_info=True)
    return jsonify({"error": "service unavailable"}), 503
```

Never put `str(exc)` or `{exc}` inside any `jsonify()` call.

---

## Step 4 — Dashboard template

Create `projects/home-hub/dashboard/templates/index.html`.

React + Babel via CDN. Fetches from `/api/hub/overview` every 30 seconds.

### Layout

**Header:**
- Left: amber square logo icon, "Home Automation" (bold), "Kigali · Home Automation" (muted)
- Right: global status pills (MQTT online/offline, InfluxDB online/offline),
  any system-level alert (e.g. "Solar offline"), live badge "⟳ 30S",
  logged-in username + logout button

**Services grid** — one card per service, 3-column responsive grid:
- Card header: service name (label, muted caps), online/offline/waiting badge
- Card body: two metric tiles side by side (key_metrics fields)
- Card footer: port number (muted), "Open →" link to service URL
- Card state when online=false: metrics show "—", muted border
- Card state when data_available=false but online=true: metrics show "—",
  amber "Waiting" badge

**Infrastructure row** — three chips below the grid:
- InfluxDB · :8086 · online/offline dot
- Mosquitto MQTT · :1883 · online/offline dot
- Grafana · :3000 · online/offline dot

**Placeholder state** (no data from `/api/hub/overview`):
- All metric values show "—"
- Info banner: "Connecting to services..."
- All cards visible

---

## Step 5 — Dockerfile

Pattern: `projects/lighting-control/Dockerfile` exactly.
Build context: repo root (set in docker-compose).
PYTHONPATH=/app after WORKDIR.
Default CMD: Flask dashboard (hub has no separate collector).

```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY projects/home-hub/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY shared /app/shared
COPY projects/home-hub /app/projects/home-hub
WORKDIR /app/projects/home-hub
ENV PYTHONPATH=/app
EXPOSE 5006
CMD ["python", "-m", "flask", "--app", "dashboard.app", "run", "--host", "0.0.0.0", "--port", "5006"]
```

---

## Step 6 — docker-compose.yml

Add to `docker-compose.yml`:

```yaml
  home-hub:
    build:
      context: .
      dockerfile: projects/home-hub/Dockerfile
    container_name: home-hub
    restart: unless-stopped
    ports:
      - "5006:5006"
    env_file: .env
    depends_on:
      - influxdb
```

---

## Step 7 — Dev server

Create `projects/home-hub/tests/dev_server.py`.

Comment block at top:
```python
# dev_server.py — Home hub UI development server
# Serves /api/hub/* routes from fixture files.
# Use for UI testing without any sub-project running.
#
# Run:  cd projects/home-hub && python -m tests.dev_server
# Open: http://localhost:5006
#
# Switch scenarios:
#   GET /api/hub/scenario?name=all_online
#   GET /api/hub/scenario?name=some_offline
#   GET /api/hub/scenario?name=no_data
# Refresh after each.
#
# NOT for production use. Not covered by the test suite.
```

Scenarios:
```python
SCENARIOS = {
    "all_online":   {"services_online": 5, "services_total": 5},
    "some_offline": {"services_online": 3, "services_total": 5},
    "no_data":      {"services_online": 0, "services_total": 5,
                     "data_available": False},
}
```

Serve `/api/hub/overview` from `tests/fixtures/hub_overview.json`.
Serve `/` — the real dashboard template (auth bypassed in dev server).
Run on port 5006.

---

## Step 8 — Tests

**Target: 45+ tests**

### test_app.py required coverage

`GET /api/hub/overview`:
- All services online → correct shape, services_online=5
- One service times out → online=false for that service, others unaffected
- All services offline → services_online=0, HTTP 200 (not 503)
- Service returns 500 → online=false, does not raise
- InfluxDB health check online
- InfluxDB health check offline
- Grafana health check online/offline
- MQTT check online/offline
- `extract_metrics("lighting_control", {...})` → correct fields
- `extract_metrics("water_monitor", [...])` → correct tank list
- `extract_metrics("solar_battery", {...})` → correct fields
- `extract_metrics("dns_monitor", {...})` → correct fields
- `extract_metrics("power_dashboard", {...})` → correct fields
- `extract_metrics("unknown_service", {})` → empty dict, no raise
- Missing metric key → None value, no raise

`GET /api/hub/status`:
- Returns {online: true, services_total, services_online}

`GET /`:
- Unauthenticated → redirect to /auth/login
- Authenticated → 200

---

## Step 9 — Verification

```bash
python -m py_compile projects/home-hub/dashboard/app.py
python -m py_compile projects/home-hub/tests/dev_server.py

.venv/bin/python -m pytest projects/home-hub/tests/ -v --tb=short

.venv/bin/python -m pytest projects/lighting-control/tests/ -v --tb=short
.venv/bin/python -m pytest projects/solar-battery/tests/ -v --tb=short
.venv/bin/python -m pytest projects/power-dashboard/tests/ -v --tb=short
.venv/bin/python -m pytest projects/water-monitor/tests/ -v --tb=short
```

Dev server smoke test:
```bash
cd projects/home-hub
timeout 5 ../../.venv/bin/python -m tests.dev_server || true
```

Targets:
- home-hub: **45+ passing**
- All existing suites: no regression

Also verify:
```bash
grep -n "str(exc)\|{exc}" projects/home-hub/dashboard/app.py
# Must return zero matches inside jsonify() calls
```

---

## Constraints

- `hub.yaml` is the single source of truth for service URLs and ports
- Service URLs overridable via env vars — never hardcoded in Python
- Each sub-project fetch is independent — one timeout never blocks others
- `extract_metrics` never raises regardless of input shape
- Auth Blueprint registered — `/` requires login, `/api/hub/*` is public
- `SECRET_KEY` from env via `os.getenv()` with dev fallback
- No `print()` — use `app.logger`
- No `str(exc)` inside `jsonify()`
- No bare `except` clauses
- PYTHONPATH=/app in Dockerfile — mandatory

---

## Completion summary

Provide:
1. Files created or modified with line counts
2. Test count: test_app.py total
3. Confirm auth Blueprint registered and `/` redirects when unauthenticated
4. Confirm dev server starts without import errors
5. Confirm PYTHONPATH=/app in Dockerfile
6. Any sub-project endpoint shape assumptions made
7. Suggested Phase 3 branch: feature/dashboard-guards

Then update `AGENTS.md` per the session close instructions in `instructions.md` and commit.
