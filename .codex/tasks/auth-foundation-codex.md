# Task: auth-foundation

**Branch:** `feature/auth-foundation`
**Scope:** `shared/auth/`, `scripts/`, `infrastructure/`, `.env.example`, `.gitignore`,
and one integration target (see note below).

**Prerequisite note:** If `feature/home-hub` is on `main`, the integration target
is `projects/home-hub/dashboard/app.py`. If home-hub is not yet built, use
`projects/lighting-control/dashboard/app.py` instead. Only one integration
target this session — the remaining dashboards are wired in Phase 3.

## Allowed files to create or modify

```
shared/auth/__init__.py                              CREATE
shared/auth/manager.py                               CREATE
shared/auth/decorators.py                            CREATE
shared/auth/blueprint.py                             CREATE
shared/auth/templates/auth/login.html                CREATE
shared/auth/tests/__init__.py                        CREATE
shared/auth/tests/test_manager.py                    CREATE
shared/auth/tests/test_decorators.py                 CREATE
shared/auth/tests/test_blueprint.py                  CREATE
infrastructure/users.yaml.example                    CREATE
scripts/hash_password.py                             CREATE
.env.example                                         MODIFY
.gitignore                                           MODIFY
projects/home-hub/dashboard/app.py                   MODIFY (register blueprint only)
  OR projects/lighting-control/dashboard/app.py      MODIFY (if home-hub not on main)
AGENTS.md                                            MODIFY (session close only)
```

Do not touch any file outside this list without explicit permission.
Do not modify any existing route in any `app.py`.

---

## Context

Auth is a shared concern — five dashboards plus the home hub all need it.
The implementation lives entirely in `shared/auth/` and is registered into
each Flask app as a Blueprint. No dashboard duplicates auth logic.

Roles: `admin` (full access) and `user` (read + lighting toggles only).
Users are stored in `infrastructure/users.yaml` with bcrypt-hashed passwords.
Sessions use Flask signed cookies backed by a `SECRET_KEY` from `.env`.

This phase builds and tests the shared module in isolation, then wires it
into the first integration target as proof of concept.

---

## Step 1 — Read first

Before writing any code, read:
- `shared/db/influx.py` — pattern for shared module structure
- `shared/mqtt/client.py` — pattern for env var access in shared modules
- `projects/lighting-control/dashboard/app.py` — Flask app patterns, .env loading
- `projects/solar-battery/dashboard/app.py` — exception handling patterns

---

## Step 2 — Environment variables

Add to `.env.example`:

```
# Auth
SECRET_KEY=                    # generate: python -c "import secrets; print(secrets.token_hex(32))"
AUTH_USERS_FILE=infrastructure/users.yaml
AUTH_SESSION_LIFETIME_HOURS=24
```

Add to `.gitignore` (users.yaml contains password hashes — never commit it):

```
infrastructure/users.yaml
```

---

## Step 3 — User store

Create `infrastructure/users.yaml.example` (committed as template, real file gitignored):

```yaml
# Copy to infrastructure/users.yaml and replace hashes.
# Generate hashes: python scripts/hash_password.py <password>
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

Valid roles: `admin`, `user`. Any other value raises `ValueError` on load.

---

## Step 4 — Hash password script

Create `scripts/hash_password.py`:

```python
#!/usr/bin/env python3
"""Generate a bcrypt password hash for use in infrastructure/users.yaml.

Usage:
    python scripts/hash_password.py mysecretpassword
    python scripts/hash_password.py          # prompts securely
"""
```

Requirements:
- Accepts password as CLI arg or prompts with `getpass` if omitted
- Prints the bcrypt hash to stdout
- Exits with code 1 if bcrypt is unavailable
- No other output — hash must be paste-ready

---

## Step 5 — shared/auth/manager.py

```python
def users_file_path() -> Path:
    # Returns Path from AUTH_USERS_FILE env var, default infrastructure/users.yaml
    # Resolves relative to repo root (parent of shared/)

def load_users() -> list[dict]:
    # Reads and validates users.yaml.
    # Raises FileNotFoundError if file missing.
    # Raises ValueError if any user entry is missing required fields
    #   (username, password_hash, role) or has an invalid role.
    # Returns list of user dicts.

def find_user(username: str) -> dict | None:
    # Returns first user matching username, or None.
    # Case-insensitive username match.

def verify_password(username: str, password: str) -> bool:
    # Returns True if user exists and bcrypt hash matches password.
    # Returns False (never raises) for unknown username or wrong password.
    # Uses bcrypt.checkpw — timing-safe.

def get_session_user() -> dict | None:
    # Reads current user from flask.session.
    # Returns dict with username, role, display_name or None if not logged in.

def login_user(username: str) -> None:
    # Writes username, role, display_name, logged_in_at to flask.session.
    # Calls session.modified = True.
    # Raises ValueError if username not found in users store.

def logout_user() -> None:
    # Clears flask.session entirely.
```

All functions that read users reload from file on every call — no in-memory
cache. File is small; freshness matters more than speed.

---

## Step 6 — shared/auth/decorators.py

```python
def require_auth(f):
    """Redirect to /auth/login?next=<url> if session has no logged-in user.
    For API routes (Accept: application/json or X-Requested-With: XMLHttpRequest),
    return 401 + {"error": "authentication required"} instead of redirecting."""

def require_admin(f):
    """Apply after @require_auth. Return 403 + {"error": "admin access required"}
    if the logged-in user's role is not 'admin'."""
```

`require_admin` must work correctly when stacked:
```python
@app.route("/admin/users")
@require_auth
@require_admin
def admin_users(): ...
```

---

## Step 7 — shared/auth/blueprint.py

Flask Blueprint registered with `url_prefix="/auth"`.

```
POST /auth/login
     Body (JSON or form): {username, password, remember: bool (optional)}
     Success: set session, return 200 + {username, role, display_name}
              If request is HTML (not JSON/XHR), redirect to `next` param
              or "/" after setting session.
     Failure: 401 + {"error": "invalid credentials"}
     Already logged in: 200 + current user from get_session_user()

POST /auth/logout
     Clears session via logout_user().
     Always: redirect to /auth/login (HTML) or 200 + {"logged_out": true} (JSON/XHR)

GET  /auth/me
     Logged in:  200 + {username, role, display_name, logged_in: true}
     Not logged in: 200 + {logged_in: false}
     Never 401 — this route is always public.
```

Blueprint name: `auth`. Template folder: `shared/auth/templates`.

---

## Step 8 — shared/auth/templates/auth/login.html

Standalone login page. Plain HTML + inline CSS only — no CDN, no React.
Must work without JavaScript.

Required elements:
- Form: `POST /auth/login` with `username`, `password`, hidden `next` field
- Error message area: shown when `error` is in template context
- Submit button
- Minimal styling consistent with existing dashboards (white background,
  clean card layout, same font stack)

Do not use Jinja2 `{% raw %}` blocks — this template has no JSX.

---

## Step 9 — Integration target

**If home-hub is on main**, modify `projects/home-hub/dashboard/app.py`:

```python
from shared.auth.blueprint import auth_bp
from shared.auth.decorators import require_auth

app.secret_key = os.getenv("SECRET_KEY", "dev-key-replace-in-production")
app.register_blueprint(auth_bp)

# Add @require_auth to the main index route only.
# Do not add it to /api/auth/* routes (already public via blueprint).
# Do not add it to any other existing routes this session.
```

**If home-hub is not on main**, apply the same three changes to
`projects/lighting-control/dashboard/app.py`.

This integration step is proof of concept only — full roll-out to all
dashboards happens in Phase 3.

---

## Step 10 — shared/auth/__init__.py

Export the public API:

```python
from .manager import find_user, get_session_user, load_users, login_user, logout_user, verify_password
from .decorators import require_admin, require_auth
from .blueprint import auth_bp

__all__ = [
    "auth_bp",
    "find_user", "get_session_user", "load_users",
    "login_user", "logout_user", "verify_password",
    "require_auth", "require_admin",
]
```

---

## Step 11 — Tests

| File | Minimum | Focus |
|---|---|---|
| `test_manager.py` | 30 | Pure unit tests, mock filesystem |
| `test_decorators.py` | 20 | Minimal Flask app fixture |
| `test_blueprint.py` | 20 | Flask test client, mock manager |

**Total target: 70+**

### test_manager.py required coverage
- `load_users`: valid file, missing file → FileNotFoundError, missing field → ValueError
- `load_users`: invalid role → ValueError, empty file → empty list
- `find_user`: known username, unknown username, case-insensitive match
- `verify_password`: correct password, wrong password, unknown user
- `verify_password`: never raises on bad input
- `get_session_user`: session set → dict returned, session empty → None
- `login_user`: sets all required session keys, unknown user → ValueError
- `logout_user`: clears session
- `users_file_path`: env var set, env var unset → default path

### test_decorators.py required coverage
- `@require_auth`: unauthenticated HTML request → redirect to /auth/login
- `@require_auth`: unauthenticated JSON request → 401 + error body
- `@require_auth`: authenticated → passes through to route
- `@require_auth`: `next` param preserved in redirect URL
- `@require_admin`: admin role → passes through
- `@require_admin`: user role → 403
- `@require_admin`: unauthenticated → 401 (require_auth fires first)
- Stacked decorators work in correct order

### test_blueprint.py required coverage
- `POST /auth/login`: valid credentials → 200 + user dict, session set
- `POST /auth/login`: invalid credentials → 401
- `POST /auth/login`: JSON body and form body both accepted
- `POST /auth/login`: `next` param → redirect after HTML login
- `POST /auth/login`: already logged in → 200 + current user
- `POST /auth/logout`: clears session, redirects (HTML)
- `POST /auth/logout`: JSON request → 200 + {logged_out: true}
- `GET /auth/me`: logged in → full user dict
- `GET /auth/me`: not logged in → {logged_in: false}, HTTP 200

---

## Step 12 — Verification

```bash
python -m py_compile shared/auth/manager.py
python -m py_compile shared/auth/decorators.py
python -m py_compile shared/auth/blueprint.py
python -m py_compile scripts/hash_password.py

.venv/bin/python -m pytest shared/auth/tests/ -v --tb=short

# Confirm existing suites unaffected
.venv/bin/python -m pytest projects/lighting-control/tests/ -v --tb=short
.venv/bin/python -m pytest projects/solar-battery/tests/ -v --tb=short
.venv/bin/python -m pytest projects/power-dashboard/tests/ -v --tb=short
.venv/bin/python -m pytest projects/water-monitor/tests/ -v --tb=short
```

Smoke test the hash script:
```bash
echo "testpassword" | .venv/bin/python scripts/hash_password.py testpassword
# Must print a bcrypt hash starting with $2b$
```

Targets:
- auth tests: **70+ passing**
- All existing suites: no regression

Also verify:
```bash
grep -n "str(exc)\|{exc}" shared/auth/blueprint.py
# Must return zero matches inside jsonify() calls
```

---

## Constraints

- `shared/auth/` has zero dependency on any project — no imports from `projects/`
- `bcrypt` is the only new dependency — add to `shared/auth/requirements.txt`
  AND to the integration target's `requirements.txt`
- `SECRET_KEY` always read from env via `os.getenv()` with a fallback of
  `"dev-key-replace-in-production"` — never hardcoded, never crash on missing key
- `users.yaml` is never committed — `.gitignore` addition is mandatory this session
- `infrastructure/users.yaml.example` IS committed — it is the template
- Password comparison always via `bcrypt.checkpw` — never string equality
- `require_admin` never bypasses `require_auth` — always check auth first
- No `print()` — use `app.logger` inside blueprint, `logging` module in manager
- No bare `except` clauses
- Existing routes in any `app.py` must not be modified

---

## Completion summary

Provide:
1. Files created or modified with line counts
2. Test count: test_manager / test_decorators / test_blueprint / total
3. Integration target used (home-hub or lighting-control)
4. Confirm `infrastructure/users.yaml` is gitignored
5. Confirm `infrastructure/users.yaml.example` is committed
6. Confirm no existing routes were modified
7. bcrypt hash of "testpassword" from the script (for verification)
8. Suggested Phase 3 branch name

Then update `AGENTS.md` per the session close instructions in `instructions.md` and commit.
