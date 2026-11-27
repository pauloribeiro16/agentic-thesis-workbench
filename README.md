# Agentic Thesis Workbench

A local, model-agnostic web workbench for writing a thesis with several AI agents under the author's control.

- **Zero dependencies:** Python 3.11+ standard library and vanilla HTML/CSS/JS. No build step; the test suite runs in seconds.
- **Bring your own format, citations and agents:** `thesis.toml` says where things are; your own plan
  (`.thesis/plan.toml`: chapters, pages, words, sections, what each chapter must argue, writing rules) is kept
  apart. The engine ships with **no limits of its own** — an unset rule reports "not configured".
- **Comments that are easy to make and easy to close:** select text, press `C` (comment) or `S` (suggest a change);
  agents answer with before/after proposals; you accept, an implementer applies, you confirm — all in a *To close* queue.
- **Roles as templates for sub-agents:** reviewers (tone, narrative, consistency, citations, examiner), drafters and an
  implementer, exportable to Claude Code sub-agents, Agent Skills (`SKILL.md`) or plain prompts.
- **Pages, not words:** the page budget comes from the last LaTeX/PDF build (references and in-text citations
  left out); words only translate it with each chapter's own words per page. Compile from the Manuscript and
  read the PDF next to your comments — comments always stay on the text.
- **Change proposals** decided item by item, sealed, registered in the dialogue and applied by an implementer.
- **Quality checks as plugins:** structure, formatting, citations, style, page budget, governance and agent reviews —
  no global score, every check names its rule. Add your own rules in `.thesis/plugins/`.
- **Human-in-the-loop by construction:** agents only propose; approvals are HMAC-sealed by the author's key, so an
  agent cannot approve a decision or a text change by editing a file.
- **Interface in English or Portuguese** (`[ui] locale`); data, files and code stay in English.
- **Standalone or embedded** behind a host portal (`--host-shell second-brain`).

## Quick start

```bash
python3 -m atw serve --workspace examples/sample-thesis      # http://127.0.0.1:8765
python3 -m atw init  --workspace /path/to/your-thesis        # thesis.toml, .thesis/, AGENTS.md
python3 -m atw check --workspace /path/to/your-thesis        # quality checks in the terminal
```

Working with agents:

```bash
python3 -m atw task new --workflow chapter-review --chapter 3 --workspace /path/to/thesis
# tell your agent: "Do task T-001 (read .thesis/tasks/T-001.json)"
python3 -m atw review validate T-001 --workspace /path/to/thesis
python3 -m atw roles export --to claude --workspace /path/to/thesis   # or: skills | markdown
```

Run the tests: `python3 -m unittest discover -s tests`.

## Layout

```
atw/            engine: config, formats, citations, dialogue (governance), comments, tasks, roles, quality, plugins, server
atw/builtin/    built-in plugins (formats, checks) — same contract as third-party ones
atw/roles/      built-in roles (ROLE.md) and workflows.toml
web/            single-page app + i18n/{en,pt}.json
docs/           AGENT_MANUAL.md · SCHEMAS.md · PLUGINS.md
```

## Embedding in a host portal

All API calls are relative (`api/...`), so the app works at `/` and under a prefix such as `/thesis/`:

```toml
[[area]]
id = "thesis"
url = "/thesis/"
  [area.service]
  command = ["python3", "-m", "atw", "serve", "--workspace", "/path/to/thesis", "--port", "{port}", "--host-shell", "second-brain"]
  health = "/api/etag"
```

`GET api/summary` gives a compact status for the host's home page.

## Security

The server binds to 127.0.0.1, rejects requests whose `Host` or `Origin` is not local (DNS-rebinding and
cross-site protection) and only accepts JSON POSTs. Local plugins in `.thesis/plugins/` are Python code from the
thesis repository: only enable folders you trust. The signing key lives outside the repository
(`[agents] key_path`, `ATW_SIGNING_KEY`, or `~/.config/agentic-thesis-workbench/moderator.key`). The workbench
**never creates a key implicitly** — run `python3 -m atw key init` once — so two tools reading the same files never
end up with two keys and two versions of what was approved. Set `require_key_path = true` to forbid the default.

## Documentation

- [docs/AGENT_MANUAL.md](docs/AGENT_MANUAL.md) — how agents do tasks, run roles and customise the workbench
- [docs/SCHEMAS.md](docs/SCHEMAS.md) — task, review, comment, ledger and style-guide formats
- [docs/PLUGINS.md](docs/PLUGINS.md) — writing checks, formats, citation providers and roles
- [docs/RECIPES.md](docs/RECIPES.md) — carry the workbench inside the thesis, compile chapters from the manuscript, keep generated LaTeX in sync
- [thesis.example.toml](thesis.example.toml) — annotated configuration

## License

MIT — see [LICENSE](LICENSE).
