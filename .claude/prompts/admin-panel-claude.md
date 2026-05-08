# Admin panel — user management CRUD, audit log, admin UI in home-hub

**Branch:** `feature/admin-panel`
**Prerequisite:** Run `session-open.md` before starting.

---

## Situation

Phase 5 adds user management and an activity log to the platform. Three areas
change: `shared/auth/manager.py` gains CRUD functions for users.yaml,
a new `shared/auth/audit.py` module writes activity events to InfluxDB, and
the home hub gains an `/admin` page with a full user management UI. The
Settings link in the hub header (a placeholder since Phase 4) becomes
functional. The lighting-control toggle route gains audit log writes.

---

## Architecture decisions to enforce

### CRUD is atomic — read, modify in memory, write all

`create_user`, `update_user`, `delete_user`, and `set_password` all call
`_save_users()` which writes the entire user list back to users.yaml in one
operation. No function writes individual fields or appends partial data.
This prevents corrupt states if two writes race. Reject any implementation
that opens users.yaml in append mode or writes partial YAML.

### password_hash never leaves the server

The `/api/admin/users` endpoint and all admin route responses return only
`{username, role, display_name}`. `password_hash` must never appear in any
`jsonify()` return value. Verify with:
```bash
grep -n "password_hash" projects/home-hub/dashboard/app.py
```
Must return zero matches inside any `return jsonify(...)` call.

### Server-side enforcement of self-protection rules

Two rules are enforced in Python, not just in the UI:
1. Admin cannot change their own role — check `get_session_user()["username"] != username`
   before calling `update_user()` when `role` is in the update body
2. Admin cannot delete themselves — same check before `delete_user()`

These checks must be in the route handler, not in `manager.py` (which has no
concept of "current user"). The UI disables these buttons too, but the API
must reject them independently.

### write_audit_event never raises

`shared/auth/audit.py` wraps every InfluxDB interaction in a broad
`except Exception` — the only permitted use of bare except in this codebase.
Audit log failure must never break a user-facing action. Test this explicitly:
mock InfluxDB to raise and confirm `write_audit_event` returns normally.

### Audit log only records successful actions

`write_audit_event` is called after a successful operation, never before and
never inside an except block. A failed toggle, failed user create, or failed
password reset must not produce an audit entry.

### GET /api/admin/audit-log returns [] when InfluxDB is down

Unlike other InfluxDB-dependent routes that return 503, the audit log returns
an empty list when InfluxDB is unavailable. The audit log is informational —
the admin panel must still load and show user management even with no data.

---

## Reference files to read before reviewing

1. `shared/auth/manager.py` — existing functions, `_save_users` implementation
2. `shared/auth/audit.py` — `write_audit_event` and its exception handling
3. `shared/db/influx.py` — wrapper used by audit.py
4. `projects/home-hub/dashboard/app.py` — confirm `require_admin` imported, admin routes present
5. `projects/home-hub/dashboard/templates/index.html` — confirm Settings link no longer has `pointer-events: none`

---

## Security checklist

```bash
# password_hash never in API responses
grep -n "password_hash" projects/home-hub/dashboard/app.py
# Zero matches inside jsonify() calls

# No str(exc) in jsonify
grep -n "str(exc)\|{exc}" projects/home-hub/dashboard/app.py
# Zero matches

# Admin routes guarded
grep -n "require_admin" projects/home-hub/dashboard/app.py
# Must appear on all /api/admin/* routes and /admin route

# Toggle route changed from @require_admin to @require_auth
grep -n "require_admin" projects/lighting-control/dashboard/app.py
# The /set route must NOT appear in this output — only read-only or other write routes

# Settings link is now functional
grep -n "pointer-events" projects/home-hub/dashboard/templates/index.html
# Must return zero matches (placeholder CSS removed)

# Audit write only on success
grep -B5 "write_audit_event" projects/home-hub/dashboard/app.py
# Each call must be preceded by the successful operation, not inside except
```

---

## Test cases to spot-check

### shared/auth/manager.py
- `create_user("admin", "pass", "admin")` → raises `ValueError` (username taken)
- `create_user("newuser", "pass", "superuser")` → raises `ValueError` (invalid role)
- `create_user("newuser", "", "user")` → raises `ValueError` (empty password)
- New user's `password_hash` in users.yaml starts with `$2b$` (bcrypt)
- `delete_user` on the only admin → raises `ValueError`
- `set_password("x", "newpass")` → new hash verifies with `verify_password`

### shared/auth/audit.py
- `write_audit_event(...)` with InfluxDB mocked to raise `Exception` → returns `None`, no raise
- `write_audit_event(...)` with empty optional fields → no crash

### home-hub admin routes
- `GET /api/admin/users` response contains no `password_hash` key in any item
- `PUT /api/admin/users/<own_username>` with `{"role": "user"}` → 400
- `DELETE /api/admin/users/<own_username>` → 400
- `GET /api/admin/audit-log` with InfluxDB mocked to raise → 200 + `[]`

### lighting-control
- `POST /api/lighting/devices/<id>/set` succeeds → `write_audit_event` called once
- `POST /api/lighting/devices/<id>/set` MQTT fails → `write_audit_event` not called

---

## Admin UI to verify manually

```bash
cd projects/home-hub
../../.venv/bin/python -m flask --app dashboard.app run --port 5006
```

1. Log in as admin → hub loads
2. Click Settings link in header → `/admin` page loads
3. User table shows all users from users.yaml (no password_hash visible)
4. Add user form → submit → user appears in table
5. Edit role on a non-self user → role changes
6. Edit/delete buttons on own row are disabled
7. Activity log section shows "No activity recorded" (InfluxDB likely empty locally)
8. Log in as non-admin user → Settings link absent from hub header
9. Direct navigation to `/admin` as non-admin → 403

---

## Test targets

| Suite | Before | After |
|---|---|---|
| shared/auth | 73 | 103+ |
| home-hub | 48 | 68+ |
| lighting-control | 96 | 101+ |
| water-monitor | 170 | 170 (unchanged) |
| power-dashboard | 160 | 160 (unchanged) |
| solar-battery | 122 | 122 (unchanged) |

---

## Constraints

- `password_hash` never in any API response
- CRUD writes are atomic via `_save_users()`
- Self-role-change and self-delete blocked server-side (not just UI)
- `write_audit_event` never raises — broad except is intentional here only
- Audit written only after successful operations
- `GET /api/admin/audit-log` returns `[]` on InfluxDB failure (not 503)
- Settings link in index.html must be functional — `pointer-events: none` removed
- No `print()` — use `app.logger`
- No `str(exc)` inside `jsonify()`

---

## Completion summary

Provide:
1. Files created or modified with line counts
2. New test count: shared/auth / home-hub / lighting-control / total
3. Grep result: zero `password_hash` matches inside jsonify() in app.py
4. Confirm self-role-change and self-delete blocked server-side
5. Confirm `write_audit_event` tested with forced InfluxDB failure
6. Confirm Settings link is functional (pointer-events removed)
7. Confirm audit log returns `[]` on InfluxDB failure

Then run `session-close.md`.
