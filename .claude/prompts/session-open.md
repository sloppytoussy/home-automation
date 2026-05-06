# Session open prompt

Run this at the start of every Claude Code session. Ensures the agent
orients correctly before touching any code.

---

## Session start — orient before acting

Before writing any code or running any commands:

1. **Read `AGENTS.md`** in the repo root. This is the authoritative source
   for project context, hardware, architecture decisions, port assignments,
   rules, and current roadmap state.

2. **Read the task prompt** for this session (the file or message that
   describes what to build). Do not begin until both are read.

3. **Check git state:**
   ```bash
   git status
   git log --oneline -5
   git branch
   ```
   Confirm you are on the correct feature branch. Never commit directly
   to `main`.

4. **Read reference files** as specified in the task prompt before writing
   any new code. The task prompt will name specific files to read first.

5. **Run existing tests** to confirm the baseline is green before making
   changes:
   ```bash
   python -m pytest projects/water-monitor/tests/ -v --tb=short
   python -m pytest projects/<active-project>/tests/ -v --tb=short
   ```
   If baseline tests are red, report it before proceeding — do not
   assume failures are pre-existing without checking `AGENTS.md`
   known issues first.

6. **State your plan** in one paragraph before writing code. Include which
   files you will create or modify and in what order.

Only after completing all six steps should you begin the task.
