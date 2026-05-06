# Session close prompt

Run this as the final step of every Claude Code session before committing
and pushing. Keeps AGENTS.md accurate without manual maintenance.

---

## Final step — update AGENTS.md

Before closing this session, update `AGENTS.md` in the repo root:

1. **Roadmap** — check off any items completed this session. If an item is
   fully done and merged, move it to a `### Completed` subsection at the
   bottom of the roadmap block rather than deleting it. Future sessions use
   the completed list to understand what patterns already exist.

2. **Branch state** — update the branch state table to reflect the current
   state of `main` and any active feature branches. Include the latest commit
   hash and a one-line description.

3. **Architecture decisions** — if any decision was made this session that
   affects how other projects or future sessions should behave (new config
   schema, new shared library function, new hardware finding), add it to the
   Architecture decisions section. One sentence per decision is enough.

4. **Hardware findings** — if anything was discovered about specific device
   behaviour (Shelly topic format edge cases, Victron register quirks, IotaWatt
   REST pagination, etc.), add it to the Hardware context table or as a note
   beneath it.

5. **Known issues** — if any pre-existing issues were discovered but not fixed
   (out of scope, deferred, or intentional), add them to a `## Known issues`
   section so the next session does not re-investigate them.

6. **Rules** — do not modify the Rules section unless a rule is being
   explicitly added or removed by the project owner.

7. **Commit AGENTS.md** as part of the final commit of the session, not as a
   separate commit. Message format:

   ```
   chore: update AGENTS.md for <branch-name> session
   ```

Do not add speculative future items to the roadmap. Only add things that have
been explicitly discussed and agreed on.
