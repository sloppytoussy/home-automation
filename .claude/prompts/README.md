# Prompt library

Reusable Claude Code prompts for this project. Every session should use
`session-open.md` at the start and `session-close.md` at the end.
Task prompts go between them.

## How to use

### Starting a session
1. Open Claude Code in the repo root
2. Paste the contents of `session-open.md` — this orients the agent
3. Paste the contents of the relevant task prompt
4. The task prompt will tell Claude Code what to read and build

### Closing a session
The task prompt's final step will instruct Claude Code to run
`session-close.md`. This updates `AGENTS.md` and commits it as part
of the final commit.

### Adding a new task prompt
Create a new `.md` file in this directory named after the feature branch,
e.g. `solar-battery-victron.md`. Follow the structure of
`power-dashboard-collector.md`:
- Context
- Step 1: files to read first
- Numbered implementation steps
- Test requirements per file
- CI validation
- Constraints
- Completion summary (always ends with "then run session-close.md")

## Prompt index

| File | Branch | Status |
|---|---|---|
| `session-open.md` | All sessions | Permanent |
| `session-close.md` | All sessions | Permanent |
| `power-dashboard-collector.md` | `feature/power-dashboard-collector` | Active |

## Naming convention

Task prompt files are named after their target branch with the
`feature/` prefix dropped:

```
feature/power-dashboard-collector  →  power-dashboard-collector.md
feature/solar-battery-victron      →  solar-battery-victron.md
feature/water-monitor-phase-3      →  water-monitor-phase-3.md
```
