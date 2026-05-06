# Codex instructions

## Read before acting

1. Read `AGENTS.md` in the repo root before touching any file.
2. Read the relevant task file from `.codex/tasks/` if one exists for
   the current branch or topic.
3. Run `git status` and `git log --oneline -5` to orient before editing.
4. State your plan before writing code.

---

## Project layout

```
projects/
  power-dashboard/     Port 5001
  water-monitor/       Port 5002
  solar-battery/       Port 5003
  dns-monitor/         Port 5000
shared/
  db/influx.py         InfluxDB 2.7 wrapper — use this, never duplicate
  mqtt/client.py       Mosquitto helper — use this, never duplicate
  utils/               Structured logging — use this, never print()
infrastructure/
  docker/
  grafana/
  influxdb/
  nginx/
```

---

## Environment

- Python 3.9.6 — use `from __future__ import annotations` for union types
- Virtual environment: `.venv/` at repo root
- `docker-compose` (hyphenated) — `docker compose` is not available
- Flask templates use React + Babel via CDN — no build step required
- InfluxDB env vars: always `os.getenv()` with safe fallback, never
  `os.environ[]` directly

---

## Commands

```bash
# Install
pip install -r projects/<project>/requirements.txt --break-system-packages

# Test (always run before and after changes)
python -m pytest projects/<project>/tests/ -v --tb=short

# Test all
python -m pytest projects/ -v --tb=short

# Lint check
python -m py_compile projects/<project>/dashboard/app.py
python -m py_compile projects/<project>/collector/*.py

# Run app
cd projects/<project>
python -m flask --app dashboard.app run --host 0.0.0.0 --port <port>
```

---

## Non-negotiable rules

- Never commit to `main` directly. Always work on a feature branch.
- Never use `print()`. Use `shared/utils/` structured logging.
- Never hardcode IPs, ports, credentials, or rate values in Python source.
- Never use bare `except`. Catch specific exceptions.
- Never use `shell=True` in subprocess calls.
- Never modify manual entry routes in any `dashboard/app.py`.
- Never duplicate InfluxDB, MQTT, or logging logic — use `shared/`.
- Never add Codex, ChatGPT, OpenAI, or any AI tool as a co-author in commits.
  Commits must show only the human author.
- Do not rewrite files outside the stated scope of the task.
- Do not modify the DNS monitor test suite unless explicitly asked —
  it has a pre-existing `requests_mock` fixture failure that is out of scope.
- Run tests before and after every change. Report failures before proceeding.
- `package-lock.json` in the repo root is accidental — do not commit it.

---

## Scoped edits

When a task file restricts the scope of edits, honour it strictly. If
completing the task correctly requires touching a file outside scope, stop
and report it rather than editing without permission.

---

## Commit format

```
<type>(<scope>): <short description>

types: feat, fix, test, refactor, chore, docs
scope: power-dashboard, water-monitor, solar-battery, dns-monitor, shared

Examples:
  feat(power-dashboard): add MQTT collector for Shelly Pro 3EM
  test(power-dashboard): add calculator unit tests (45 tests)
  fix(water-monitor): guard InfluxDB env vars with safe fallback
  chore: update AGENTS.md for feature/power-dashboard-collector session
```

---

## Session close — always do this last

Before finishing any task:

1. Run the full test suite for the affected project and confirm passing.
2. Run `py_compile` on every modified Python file.
3. Update `AGENTS.md`:
   - Check off completed roadmap items
   - Update branch state table
   - Add any architecture decisions made this session
   - Add any hardware findings or new gotchas
4. Commit `AGENTS.md` as part of the final commit, not separately.
5. Provide a summary: files changed, test count, open questions.
