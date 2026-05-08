# Codex session close

Run this as the final step of every Codex session, before committing.

---

## Step 1 — Full verification

```bash
# Syntax check every modified Python file
python -m py_compile projects/<active-project>/dashboard/app.py
python -m py_compile projects/<active-project>/collector/*.py

# Full test suite for the active project
.venv/bin/python -m pytest projects/<active-project>/tests/ -v --tb=short

# Regression check — confirm no other suite was broken
.venv/bin/python -m pytest projects/water-monitor/tests/ -v --tb=short
.venv/bin/python -m pytest projects/power-dashboard/tests/ -v --tb=short
.venv/bin/python -m pytest projects/solar-battery/tests/ -v --tb=short

# Confirm no str(exc) inside jsonify() calls
grep -rn "str(exc)\|{exc}" projects/<active-project>/dashboard/app.py
# Must return zero matches inside jsonify() calls.
```

All checks must pass before proceeding.

---

## Step 2 — Update AGENTS.md

In `AGENTS.md` at the repo root, update:

1. **Roadmap** — check off any items completed this session. Move fully
   completed items to a `### Completed` subsection rather than deleting them.

2. **Branch state table** — update to reflect the current branch status
   and latest commit.

3. **Architecture decisions** — add any new decisions that affect how
   other projects or future sessions should behave. One sentence each.

4. **Hardware findings** — add any device behaviour discovered this session
   (topic format quirks, register edge cases, timing issues, etc.).

5. **Known issues** — if anything was discovered but intentionally deferred,
   add it here so the next session does not re-investigate.

Do not speculate. Only record things explicitly decided or discovered this session.

---

## Step 3 — Commit

```bash
git add -A
git commit -m "<type>(<scope>): <short description>

<body describing what was built and why>"
```

Commit types: `feat`, `fix`, `test`, `refactor`, `chore`, `docs`

Always include AGENTS.md in the final commit — do not commit it separately.

---

## Step 4 — Completion summary

Output a summary block:

```
## Session complete

Branch: <branch-name>

Files created or modified:
  <file>    <line count>

Test counts:
  <test file>: <N> tests
  Total: <N> passing

Regression results:
  water-monitor:    <N> passing
  power-dashboard:  <N> passing
  solar-battery:    <N> passing

Constraints verified:
  [ ] No print() calls
  [ ] No str(exc) inside jsonify()
  [ ] No hardcoded IPs or credentials
  [ ] Null fields omitted from InfluxDB writes (if applicable)
  [ ] Gen1/Gen2 dispatch config-driven (if applicable)
  [ ] HA discovery gated on config flag (if applicable)

Open questions / follow-up for next session:
  - <any deferred items or unresolved questions>

Suggested next branch: <feature/...>
```

---

## Step 5 — Push

```bash
git push -u origin <branch-name>
```
