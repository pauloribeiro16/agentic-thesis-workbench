# AGENTS.md — how agents work in this thesis

This thesis uses Agentic Thesis Workbench. Read `docs/AGENT_MANUAL.md` in the workbench repository.

1. **Never edit chapter files** unless you are running the `implementer` role on changes the author approved and sealed.
2. **Work through tasks.** When asked to "do T-007", read `.thesis/tasks/T-007.json`, load the role it names
   (`python3 -m atw roles show <role>`), run it — as a sub-agent if your tool supports one — and write the output
   named in the packet. Then run `python3 -m atw review validate T-007 --workspace .`.
3. **Dialogue is append-only** in `.thesis/dialogue/`: `## Turn N — <Agent> (<Model>) — YYYY-MM-DD`, then
   `**Qn — Title**` and a verdict (`AGREE`, `PARTIALLY AGREE`, `DISAGREE`). Agents propose states; only the author's
   sealed decision approves.
4. **Cite only verified passages** (ledger: `.thesis/citations/ledger.json`).
5. **Change rules through configuration** (`thesis.toml`, style guide, plugins in `.thesis/plugins/`), never in the engine.
