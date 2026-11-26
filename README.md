# Agentic Thesis Workbench

A **standalone, local-first, model-agnostic web workbench** for writing, auditing, and governing academic theses with multiple AI agents under strict human-in-the-loop control.

- **Zero runtime dependencies:** Pure Python 3.11+ standard library backend + vanilla HTML/CSS/JS frontend.
- **Bring Your Own Format:** Markdown+LaTeX, pure LaTeX, or Markdown/Quarto configured via `thesis.toml`.
- **Bring Your Own Citations:** BibTeX or CSL-JSON (Zotero / Mendeley / Better BibTeX), configurable citation syntax (`author-year`, `pandoc`, `latex`), and a SHA-256 verified passage ledger.
- **Bring Your Own Agents:** Model-agnostic append-only dialogue threads with HMAC-SHA256 signed author approvals and a full [Agent Manual](docs/AGENT_MANUAL.md).
- **Structural & Consistency Checks:** Configurable word/page budgets, heading structure, citation resolution, spelling variant (`en-GB` / `en-US`), approved glossary (`style/guide.json`), formatting consistency, plus qualitative agent review slots for narrative coherence and writing tone.
- **Standalone or Embedded:** Runs independently on `127.0.0.1:8765`, or embeds cleanly behind a host portal (such as `second-brain`) using `--host-shell second-brain`.

---

## Quick Start

Run against the included sample thesis:

```bash
python3 -m atw serve --workspace examples/sample-thesis --port 8765
```

Open `http://127.0.0.1:8765`.

Initialize your own thesis repository:

```bash
python3 -m atw init --workspace /path/to/your-thesis
python3 -m atw serve --workspace /path/to/your-thesis --port 8765
```

Run structural and consistency checks from the CLI:

```bash
python3 -m atw check --workspace /path/to/your-thesis
```

---

## Embedding in a Host Platform (e.g. `second-brain`)

All frontend API requests use relative paths (`api/...`), so the workbench works identically at `/` (standalone) and under a reverse-proxy prefix like `/thesis/`.

Example `[[area]]` block:

```toml
[[area]]
id = "thesis"
name = "Thesis"
url = "/thesis/"
  [area.service]
  dir = ["~/Projects/agentic-thesis-workbench"]
  command = ["python3", "-m", "atw", "serve", "--workspace", "/path/to/your-thesis", "--port", "{port}", "--host-shell", "second-brain"]
  port = 8765
  health = "/api/etag"
```

When `--host-shell second-brain` (or `HOST_SHELL=second-brain`) is active, the workbench loads `/tokens.css` and `/nav.js` from the host and registers its sub-tabs via `window.plat.setSub(...)`.

---

## Documentation

- [docs/AGENT_MANUAL.md](docs/AGENT_MANUAL.md) — How any AI agent interacts with, reviews, and customizes the workbench.
- [thesis.example.toml](thesis.example.toml) — Complete annotated configuration reference.
