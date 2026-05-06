# .codex/

Standing instructions and task files for Codex sessions.

## Structure

```
.codex/
  instructions.md          Permanent — read at the start of every session
  coding-standards.md      Permanent — Python, Flask, testing patterns
  tasks/
    <branch-name>.md       One file per active feature branch
```

## How Codex uses these files

Codex reads `.codex/instructions.md` automatically on session start.
`coding-standards.md` is referenced by `instructions.md` and should be
read before writing any code. Task files in `tasks/` are scoped to a
specific branch — Codex reads the one matching the current branch.

## How to add a task

1. Create `.codex/tasks/<branch-name>.md` following the structure of
   `tasks/power-dashboard-collector.md`
2. Include: branch name, allowed file list, context, numbered steps,
   test targets, verification commands, completion summary
3. The task file is the source of truth for scope — Codex must not
   edit files outside the allowed list without explicit permission

## Relationship to .claude/prompts/

Both directories serve the same purpose for different agents:

| Directory | Agent | Format |
|---|---|---|
| `.codex/` | Codex (automated, headless) | Terse, strict scope lists |
| `.claude/prompts/` | Claude Code (interactive) | Detailed, step-by-step |

Task content should be equivalent — if you update one, update the other.
`AGENTS.md` is shared by both and is the single source of truth for
project-wide context.

## What not to commit from .codex/

Codex writes session logs here automatically. Do not commit them:
- Any file that looks like a session output or log dump
- The directory listing output Codex sometimes writes
- pip install output

Add these patterns to `.gitignore` to keep the directory clean:
```
.codex/session-*
.codex/*.log
```

Only the files listed in the structure above should be committed.
