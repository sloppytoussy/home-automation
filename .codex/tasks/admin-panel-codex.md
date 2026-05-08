# Task: admin-panel

**Branch:** `feature/admin-panel`
**Scope:** `shared/auth/`, `projects/home-hub/`, `projects/lighting-control/`

## Allowed files to create or modify

```
shared/auth/manager.py                                    MODIFY (add CRUD functions)
shared/auth/audit.py                                      CREATE
shared/auth/tests/test_manager.py                         MODIFY (add CRUD tests)
shared/auth/tests/test_audit.py                           CREATE
projects/home-hub/dashboard/app.py                        MODIFY (add admin routes)
projects/home-hub/dashboard/templates/admin.html          CREATE
projects/home-hub/requirements.txt                        MODIFY (add influxdb-client if missing)
projects/home-hub/tests/test_app.py                       MODIFY (add admin route tests)
projects/lighting-control/dashboard/app.py                MODIFY (add audit log to toggle)
projects/lighting-control/tests/test_app.py               MODIFY (add audit log tests)
AGENTS.md                                                 MODIFY (session close only)
```

Do not touch any file outside this list without explicit permission.

---

## Context

Phase 5 adds three things:
1. User management CRUD in `shared/auth/manager.py`
2. An audit log module `shared/auth/audit.py` that writes to InfluxDB
3. An admin panel in the home hub — `/admin` page with user management
   and activity log, accessible only to admin-role users

The admin panel activates the Settings link that has been a placeholder
in the home-hub header since Phase 4.

---

## Step 1 — Read first

Before writing any code, read:
- `shared/auth/manager.py` — existing user store functions to extend
- `shared/db/influx.py` — InfluxDB wrapper pattern to use in audit.py
- `projects/home-hub/dashboard/app.py` — existing routes and patterns
- `projects/home-hub/dashboard/templates/index.html` — dark theme CSS vars
- `projects/lighting-control/dashboard/app.py` — toggle route to add audit to

---

## Step 2 — shared/auth/manager.py: add CRUD functions

Add four functions after the existing `logout_user()`. All read the full user
list, modify in memory, and write back atomically. Never write partial updates.

```python
def _save_users(users: list[dict]) -> None:
    """Write the full user list back to users.yaml. Internal use only."""
    # Read current file content to preserve any top-level comments or structure.
    # Write using yaml.dump with default_flow_style=False.
    # Raises IOError on write failure.

def create_user(username: str, password: str, role: str,
                display_name: str = "") -> None:
    """Add a new user to users.yaml.
    Raises ValueError if:
      - username is empty or already taken (case-insensitive)
      - role not in VALID_ROLES
      - password is empty
    Hashes password with bcrypt before writing.
    Never stores plain-text password."""

def update_user(username: str, updates: dict) -> None:
    """Update role and/or display_name for an existing user.
    Allowed update keys: role, display_name.
    Raises ValueError if:
      - user not found
      - role provided but not in VALID_ROLES
    Ignores unknown keys silently."""

def delete_user(username: str) -> None:
    """Remove a user from users.yaml.
    Raises ValueError if:
      - user not found
      - deleting this user would leave zero admins"""

def set_password(username: str, new_password: str) -> None:
    """Replace a user's password hash with a new bcrypt hash.
    Raises ValueError if:
      - user not found
      - new_password is empty"""
```

---

## Step 3 — shared/auth/audit.py

Create `shared/auth/audit.py`. This module writes activity events to InfluxDB.
It must never raise — a missing or unavailable InfluxDB silently logs a warning.

```python
AUDIT_MEASUREMENT = "audit_log"

def write_audit_event(
    action: str,       # login|logout|toggle|user_create|user_update|user_delete|password_reset
    actor: str,        # username of the person performing the action
    target: str = "",  # device_id (toggle) or affected username (user CRUD)
    details: str = "", # human-readable description e.g. "turned on living_room_main"
    dashboard: str = "",  # which dashboard the action came from
    ip_address: str = "",
) -> None:
    """Write a single audit log entry to InfluxDB.
    Tags: action, actor, dashboard
    Fields: target, details, ip_address (omit empty strings)
    On any exception: log warning and return — never raise."""
```

Use `shared/db/influx.py` for the InfluxDB write. The bucket is `home_metrics`
(from `INFLUXDB_BUCKET` env var via the shared wrapper). If `INFLUXDB_URL` or
`INFLUXDB_TOKEN` env vars are absent, skip the write silently.

---

## Step 4 — home-hub/dashboard/app.py: admin routes

Add `require_admin` to the existing import from `shared.auth`.
Add `influxdb-client` to `projects/home-hub/requirements.txt` if not present.

### New route: GET /admin
```python
@app.route("/admin")
@require_auth
@require_admin
def admin_panel():
    return render_template("admin.html")
```

### API routes — all require @require_auth and @require_admin

```
GET /api/admin/users
    Returns: [{username, role, display_name}]
    password_hash MUST NEVER appear in any response.
    Empty list if users.yaml missing (not an error).

POST /api/admin/users
    Body: {username, password, role, display_name (optional)}
    Success: 201 + {username, role, display_name}
    400 if username taken, password empty, or role invalid.
    Writes audit event: action=user_create, target=new username.

PUT /api/admin/users/<username>
    Body: {role (optional), display_name (optional)}
    Success: 200 + {username, role, display_name}
    400 if actor is updating their own role.
    404 if username not found.
    Writes audit event: action=user_update, target=username.

DELETE /api/admin/users/<username>
    Success: 200 + {deleted: true}
    400 if actor is deleting themselves.
    400 if deletion would leave zero admins.
    404 if username not found.
    Writes audit event: action=user_delete, target=username.

POST /api/admin/users/<username>/reset-password
    Body: {new_password}
    Success: 200 + {reset: true}
    400 if new_password empty.
    404 if username not found.
    Writes audit event: action=password_reset, target=username.

GET /api/admin/audit-log
    Params: hours (default 24, max 168)
    Queries InfluxDB audit_log measurement.
    Returns: [{time, actor, action, target, details, dashboard}]
    Returns [] (not 503) when InfluxDB unavailable — audit log is informational.
    400 if hours invalid.
```

Exception handling — same pattern as all other dashboards:
```python
except ValueError as exc:
    app.logger.warning("Admin bad request: %s", exc)
    return jsonify({"error": "invalid input"}), 400
except Exception as exc:
    app.logger.error("Admin error: %s", exc, exc_info=True)
    return jsonify({"error": "service unavailable"}), 503
```

Never put `str(exc)` or `{exc}` inside any `jsonify()` call.

---

## Step 5 — home-hub/dashboard/templates/admin.html

Standalone page matching the home-hub dark theme (same CSS variables as
`index.html`). React + Babel via CDN. Include a "← Back to hub" link to `/`.

Fetch `currentUser` from `/auth/me` on load. If `logged_in: false` or
`role != 'admin'`, redirect to `/`.

### User management section

Table columns: Username · Role · Display name · Actions
Actions per row: **Edit role** (dropdown: admin/user) · **Reset password**
(prompts for new password) · **Delete** (confirm dialog).
Cannot edit or delete yourself — disable those action buttons on your own row.

Add user form below the table:
- Username (text input)
- Password (password input)
- Role (select: admin / user)
- Display name (text input, optional)
- Submit button: "Add user"

### Activity log section

Table columns: Time · User · Action · Target · Dashboard
Fetches from `GET /api/admin/audit-log?hours=24`.
"Last 24 hours" label. Shows "No activity recorded" when empty.
Does not show IP address in the UI (it is logged but not displayed).

---

## Step 6 — lighting-control: audit log on device toggle

Modify `POST /api/lighting/devices/<device_id>/set` in
`projects/lighting-control/dashboard/app.py`:

```python
from shared.auth.audit import write_audit_event
from shared.auth.manager import get_session_user

# Inside the /set route, after successfully publishing the MQTT command:
actor = (get_session_user() or {}).get("username", "unknown")
action_detail = "on" if body.get("on") else "off"
write_audit_event(
    action="toggle",
    actor=actor,
    target=device_id,
    details=f"turned {action_detail}",
    dashboard="lighting-control",
    ip_address=request.remote_addr or "",
)
```

`write_audit_event` must not be called if MQTT publish fails. Only audit
successful actions.

Also change the route guard on `POST /api/lighting/devices/<device_id>/set`
in `projects/lighting-control/dashboard/app.py` from `@require_admin` to
`@require_auth` only. All authenticated users should be able to toggle
devices — admin access is not required. Remove `@require_admin` from this
route only; all other POST routes in the file keep their existing guards.
This change resolves the xfail test added in Phase 4.

---

## Step 7 — Update the Settings link in home-hub index.html

In `projects/home-hub/dashboard/templates/index.html`, the Settings link
is currently `pointer-events: none` and disabled. Make it functional:

```jsx
{currentUser?.role === 'admin' && (
  <a href="/admin" style={{fontSize:'12px', color: /* muted */}}>
    Settings
  </a>
)}
```

Remove the `pointer-events: none` and `opacity: 0.6` and `cursor: not-allowed`
that marked it as a placeholder.

---

## Step 8 — Tests

**Total target: 55+ new tests across all three suites.**

### shared/auth/tests/test_manager.py additions (25+ new)

```
create_user: success, username taken → ValueError, empty username → ValueError,
  invalid role → ValueError, empty password → ValueError,
  case-insensitive duplicate detection, password stored as bcrypt hash not plain text,
  new user appears in load_users()

update_user: role updated, display_name updated, both updated,
  user not found → ValueError, invalid role → ValueError,
  unknown keys ignored

delete_user: success, user not found → ValueError,
  last admin → ValueError (cannot delete),
  non-admin deleted successfully

set_password: success, empty password → ValueError,
  user not found → ValueError, new hash verifies correctly
```

### shared/auth/tests/test_audit.py (5+ new)

```
write_audit_event: completes without raising when InfluxDB unavailable,
  does not raise on any exception type,
  accepts empty strings for optional fields
```

### projects/home-hub/tests/test_app.py additions (20+ new)

```
GET /admin: admin session → 200, user session → 403, no session → redirect
GET /api/admin/users: returns list without password_hash, empty when no file
POST /api/admin/users: success → 201, duplicate username → 400, invalid role → 400
PUT /api/admin/users/<u>: role updated, own role → 400, not found → 404
DELETE /api/admin/users/<u>: success, self → 400, last admin → 400, not found → 404
POST /api/admin/users/<u>/reset-password: success, empty password → 400, not found → 404
GET /api/admin/audit-log: returns list, InfluxDB down → [], hours=0 → 400
```

### projects/lighting-control/tests/test_app.py additions (5+ new)

```
POST /api/lighting/devices/<id>/set with auth: audit write called (mock write_audit_event)
POST /api/lighting/devices/<id>/set MQTT failure: audit write NOT called
audit called with correct actor from session
```

---

## Step 9 — Verification

```bash
python -m py_compile shared/auth/manager.py
python -m py_compile shared/auth/audit.py
python -m py_compile projects/home-hub/dashboard/app.py
python -m py_compile projects/lighting-control/dashboard/app.py

.venv/bin/python -m pytest shared/auth/tests/ -v --tb=short
.venv/bin/python -m pytest projects/home-hub/tests/ -v --tb=short
.venv/bin/python -m pytest projects/lighting-control/tests/ -v --tb=short

# Regression checks
.venv/bin/python -m pytest projects/water-monitor/tests/ -q --tb=no
.venv/bin/python -m pytest projects/power-dashboard/tests/ -q --tb=no
.venv/bin/python -m pytest projects/solar-battery/tests/ -q --tb=no
```

Also verify:
```bash
grep -n "str(exc)\|{exc}" projects/home-hub/dashboard/app.py
# Zero matches inside jsonify() calls

grep -n "password_hash" projects/home-hub/dashboard/app.py
# Must not appear in any jsonify() return value
```

Targets:
- shared/auth: 73 existing + 30 new = **103+ passing**
- home-hub: 48 existing + 20 new = **68+ passing**
- lighting-control: 96 existing + 5 new = **101+ passing**
- All other suites: no regression

---

## Constraints

- `password_hash` must never appear in any API response — verify with grep
- `create_user`, `update_user`, `delete_user`, `set_password` all write atomically
- Admin cannot change their own role — enforced server-side, not just UI
- Admin cannot delete themselves — enforced server-side
- `delete_user` prevents deleting the last admin — load users first, count admins after hypothetical removal
- `write_audit_event` never raises regardless of InfluxDB state
- Audit log is only written for successful actions — not on 4xx/5xx responses
- `GET /api/admin/audit-log` returns `[]` when InfluxDB unavailable — not 503
- Settings link in index.html must be made functional (remove placeholder CSS)
- No `print()` — use `app.logger`
- No bare `except` clauses
- All CRUD operations use `_save_users()` — never write yaml directly in route handlers

---

## Completion summary

Provide:
1. Files created or modified with line counts
2. Test count: shared/auth / home-hub / lighting-control / total new
3. Confirm `password_hash` never appears in API responses (grep result)
4. Confirm admin-cannot-change-own-role enforced server-side
5. Confirm `write_audit_event` tested for resilience (no raise)
6. Confirm Settings link is now functional in index.html
7. Confirm audit log returns `[]` (not 503) when InfluxDB unavailable

Then update `AGENTS.md` and run `session-close.md`.
