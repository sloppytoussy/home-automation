# Auth foundation — shared/auth/ module, decorators, Blueprint, login page

**Branch:** `feature/auth-foundation`
**Prerequisite:** Run `session-open.md` before starting.

---

## Situation

This session builds the authentication layer for the entire platform. It lives
in `shared/auth/` so every dashboard inherits it without duplicating logic.
The module provides: a user store backed by a YAML file with bcrypt-hashed
passwords, Flask session management, two decorators (`@require_auth`,
`@require_admin`), a Flask Blueprint with login/logout/me routes, and a
shared login page template.

At the end of this session, auth is wired into one integration target
(home-hub if on main, lighting-control otherwise) as proof of concept.
The remaining dashboards are guarded in Phase 3.

---

## Architecture decisions to enforce

### shared/auth/ has zero project dependencies

`shared/auth/` may only import from Python stdlib, `bcrypt`, `flask`, and
`yaml`. It must never import from `projects/` or from other `shared/`
sub-modules. This ensures any Flask app in the platform can adopt auth
without creating circular imports.

### Users file is never committed

`infrastructure/users.yaml` contains bcrypt-hashed passwords. It must be
in `.gitignore`. Only `infrastructure/users.yaml.example` is committed.
This is non-negotiable — verify it before the final commit:

```bash
git status infrastructure/users.yaml
# Must show nothing (not tracked, not staged)
```

### Passwords are compared with bcrypt — never string equality

`verify_password()` must call `bcrypt.checkpw(password.encode(), hash.encode())`.
No `==` comparison of passwords anywhere. Reject any implementation that
does otherwise regardless of how it is framed.

### SECRET_KEY comes from env — never hardcoded

`app.secret_key` must be set from `os.getenv("SECRET_KEY", "dev-key-replace-in-production")`.
The fallback exists only to prevent a crash in development — it must never
be used in production. The codex task adds `SECRET_KEY` to `.env.example`.

### Sessions are Flask signed cookies — no database

Flask's built-in session (signed with `SECRET_KEY`) is sufficient for a
local home automation system. No Redis, no database session store. Session
contents: `username`, `role`, `display_name`, `logged_in_at`. These are
set by `login_user()` and cleared entirely by `logout_user()`.

### Blueprint-first — auth routes belong to shared, not to any project

The `/auth/login`, `/auth/logout`, `/auth/me` routes are defined once in
`shared/auth/blueprint.py` and registered via `app.register_blueprint(auth_bp)`.
No project writes its own login route. If a project needs a custom post-login
redirect, it passes `?next=/custom-path` — the blueprint handles it.

### API vs HTML response detection

The blueprint must distinguish browser requests from programmatic API calls
and respond appropriately:
- Browser (HTML Accept header, no `X-Requested-With`): redirect on login/logout
- API (JSON Accept, `X-Requested-With: XMLHttpRequest`): return JSON, no redirect

`@require_auth` applies the same logic: redirect for browsers, 401 JSON for
API clients. This is critical for Phase 3 when dashboards have both rendered
pages and React frontends calling JSON APIs.

---

## Reference files to read before writing code

1. `shared/db/influx.py` — the pattern for shared module structure and env var access
2. `shared/mqtt/client.py` — minimal shared module with `os.getenv()` usage
3. `projects/lighting-control/dashboard/app.py` — .env loading pattern, Flask setup
4. `projects/solar-battery/dashboard/app.py` — exception handling, jsonify patterns

---

## Security checklist — verify before marking complete

```bash
# No passwords stored in plain text anywhere
grep -rn "password" shared/auth/ | grep -v "hash\|bcrypt\|checkpw\|getpass\|test\|example\|#"
# Should show only hash-related references

# No str(exc) in jsonify calls
grep -n "str(exc)\|{exc}" shared/auth/blueprint.py
# Must return zero matches

# users.yaml is gitignored
git check-ignore -v infrastructure/users.yaml
# Must show a match

# users.yaml.example is tracked
git ls-files infrastructure/users.yaml.example
# Must show the file
```

---

## Test cases to spot-check in review

### manager.py
- `verify_password("admin", "wrongpassword")` → `False` (never raises)
- `verify_password("nonexistent", "anything")` → `False` (never raises)
- `load_users()` with a user missing `password_hash` → raises `ValueError`
- `load_users()` with `role: superuser` → raises `ValueError`
- `find_user("ADMIN")` matches `username: admin` (case-insensitive)

### decorators.py
- Unauthenticated request to `@require_auth` route with `Accept: text/html`
  → 302 redirect to `/auth/login?next=<original_path>`
- Unauthenticated request with `Accept: application/json`
  → 401 + `{"error": "authentication required"}`
- Authenticated `user` role hitting `@require_admin` route → 403, not redirect
- Stacked correctly: `@require_auth` before `@require_admin` — auth checked first

### blueprint.py
- `POST /auth/login` with correct credentials sets all four session keys
- `POST /auth/login` with wrong password → 401, session not set
- `GET /auth/me` with no session → HTTP 200, `{"logged_in": false}` (not 401)
- `POST /auth/logout` clears session entirely (not just one key)

---

## Integration target

One dashboard gets auth wired this session as proof of concept:
- `projects/home-hub/dashboard/app.py` if home-hub is on main
- `projects/lighting-control/dashboard/app.py` if home-hub is not yet built

Three changes only to the integration target:
1. `app.secret_key = os.getenv("SECRET_KEY", "dev-key-replace-in-production")`
2. `app.register_blueprint(auth_bp)`
3. `@require_auth` on the main index route (the one that serves `index.html`)

Do not add `@require_auth` to any API route this session.
Do not modify any existing route logic.

---

## users.yaml.example — what to commit

```yaml
# Copy to infrastructure/users.yaml and replace hashes.
# Generate a hash: python scripts/hash_password.py <password>
users:
  - username: admin
    password_hash: "REPLACE_WITH_BCRYPT_HASH"
    role: admin
    display_name: "Admin"
  - username: viewer
    password_hash: "REPLACE_WITH_BCRYPT_HASH"
    role: user
    display_name: "Viewer"
```

The `display_name` field is optional but recommended — it appears in the
dashboard header in Phase 4.

---

## Test targets

| Suite | Target |
|---|---|
| `test_manager.py` | 30+ |
| `test_decorators.py` | 20+ |
| `test_blueprint.py` | 20+ |
| **Total auth** | **70+** |

Existing suites must remain green:

| Suite | Expected |
|---|---|
| water-monitor | 170 |
| power-dashboard | 160 |
| solar-battery | 122 |
| lighting-control | 96 |

---

## Constraints

- `shared/auth/` imports nothing from `projects/`
- `bcrypt` is the only new third-party dependency
- `infrastructure/users.yaml` is gitignored — not negotiable
- `infrastructure/users.yaml.example` is committed
- `verify_password()` uses `bcrypt.checkpw` — no string comparison
- `GET /auth/me` always returns HTTP 200 — never 401
- `logout_user()` clears the entire session — not just one key
- No `print()` — use `app.logger` (blueprint) or `logging` module (manager)
- No bare `except` clauses
- No existing routes modified in any app.py

---

## How to test auth manually after the session

```bash
# Create a real users.yaml from the example
cp infrastructure/users.yaml.example infrastructure/users.yaml

# Generate a hash for a test password and paste it in
.venv/bin/python scripts/hash_password.py mypassword

# Edit infrastructure/users.yaml with the real hash
nano infrastructure/users.yaml

# Start the integration target dashboard
cd projects/lighting-control   # or home-hub
../.venv/bin/python -m flask --app dashboard.app run --port 5005

# Open http://localhost:5005 — should redirect to /auth/login
# Log in with admin credentials — should redirect back to the dashboard
# Try GET /auth/me — should return {username, role, logged_in: true}
```

---

## Completion summary

Provide:
1. All files created or modified with line counts
2. Test count: test_manager / test_decorators / test_blueprint / total
3. Integration target used (home-hub or lighting-control)
4. Confirm `infrastructure/users.yaml` is gitignored
5. Confirm `infrastructure/users.yaml.example` is committed
6. Confirm no existing routes were modified
7. bcrypt hash output from `scripts/hash_password.py testpassword` (for verification)
8. Phase 3 branch name suggestion

Then run `session-close.md`.
