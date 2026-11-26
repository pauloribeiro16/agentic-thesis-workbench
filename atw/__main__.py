"""CLI entry point for Agentic Thesis Workbench (`python3 -m atw`)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .citations import CitationService
from .config import load_config
from .formats import FormatAdapter
from .quality import run_quality_checks
from .server import run_server

DEFAULT_TOML = """[project]
title = "{title}"
author = "Your Name"
language = "en-US"

[format]
adapter = "markdown-latex"           # markdown-latex | latex | markdown
chapters_glob = "chapters/*.md"
compiler = "none"                    # tectonic | latexmk | quarto | typst | none
word_targets = {{ default = [5000, 7500] }}

[citations]
provider = "bibtex"                  # bibtex | csl-json
bib_file = "references.bib"
library_dir = "LITERATURE"
syntax = "author-year"               # author-year | pandoc | latex
ledger_file = ".thesis/citations/ledger.json"

[agents]
dialogue_dir = ".thesis/dialogue"
proposals_file = ".thesis/proposals/proposals.json"
comments_dir = ".thesis/comments"
style_guide_file = ".thesis/style/guide.json"
moderator_name = "Author"
sign_decisions = true

[quality]
presets = ["academic-base"]
max_sentence_words = 40
forbid_first_person = false
spelling_variant = "en-US"           # none | en-GB | en-US
"""

DEFAULT_AGENTS_MD = """# AGENTS.md — Thesis Collaboration Protocol

This repository uses **Agentic Thesis Workbench** for human-in-the-loop, multi-agent thesis review.

## Core Rules
1. **Human-in-the-Loop Gate:** Never edit thesis chapter files directly without an `APPROVED` moderator decision in `{dialogue_dir}/`.
2. **Append-Only Dialogue:** Add your position at the end of the relevant thread (`{dialogue_dir}/CHn_PLAN.md`) using:
   ```markdown
   ## Turn N — <Your Agent Name> (<Model>) — YYYY-MM-DD
   ```
3. **Structured Questions:** Open each item with `**Qn — Short title**`, a verdict (`AGREE`, `PARTIALLY AGREE`, `DISAGREE`), documentary evidence, and a concrete before/after proposal before requesting approval.
4. **Verified Citations:** Never cite a source without recording the exact supporting passage in `{ledger_file}`.
5. **Customization:** To change writing rules, citation syntax, or glossary terms at the author's request, update `thesis.toml` or `{style_guide_file}` as documented in `docs/AGENT_MANUAL.md`.
"""


def cmd_init(workspace: Path) -> int:
    workspace.mkdir(parents=True, exist_ok=True)
    toml_path = workspace / "thesis.toml"
    if not toml_path.exists():
        toml_path.write_text(DEFAULT_TOML.format(title=workspace.name), encoding="utf-8")
        print(f"Created {toml_path}")
    else:
        print(f"Kept existing {toml_path}")

    cfg = load_config(workspace)
    for rel in (cfg.dialogue_dir, cfg.comments_dir, Path(cfg.ledger_file).parent, Path(cfg.style_guide_file).parent):
        (workspace / rel).mkdir(parents=True, exist_ok=True)

    guide_path = workspace / cfg.style_guide_file
    if not guide_path.exists():
        guide_path.write_text(
            json.dumps({"version": 1, "note": "Link style and glossary rules to deliberation questions.", "entries": []}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Created {guide_path}")

    agents_md = workspace / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text(
            DEFAULT_AGENTS_MD.format(
                dialogue_dir=cfg.dialogue_dir,
                ledger_file=cfg.ledger_file,
                style_guide_file=cfg.style_guide_file,
            ),
            encoding="utf-8",
        )
        print(f"Created {agents_md}")

    print("Workspace ready. Run: python3 -m atw serve --workspace", workspace)
    return 0


def cmd_check(workspace: Path, as_json: bool) -> int:
    cfg = load_config(workspace)
    chapters = FormatAdapter(cfg).discover_chapters(include_content=True)
    report = run_quality_checks(cfg, chapters, CitationService(cfg))
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        for ch in report["chapters"]:
            bads = sum(1 for c in ch["checks"] if c["state"] == "bad")
            warns = sum(1 for c in ch["checks"] if c["state"] == "warn")
            print(f"Chapter {ch['chapter']:02d} ({ch['title']}) — {ch['words']} words | bad={bads} warn={warns}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atw", description="Agentic Thesis Workbench")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="Start the local workbench HTTP server")
    p_serve.add_argument("--workspace", default=".", help="Path to thesis repository")
    p_serve.add_argument("--port", type=int, default=8765, help="Local port (127.0.0.1 only)")
    p_serve.add_argument(
        "--host-shell",
        default=os.environ.get("HOST_SHELL", "standalone"),
        choices=("standalone", "second-brain"),
        help="Use standalone shell or yield to second-brain host shell",
    )

    p_init = sub.add_parser("init", help="Initialize thesis.toml, .thesis/, and AGENTS.md in a workspace")
    p_init.add_argument("--workspace", default=".", help="Path to thesis repository")

    p_check = sub.add_parser("check", help="Run structural and consistency quality checks")
    p_check.add_argument("--workspace", default=".", help="Path to thesis repository")
    p_check.add_argument("--json", action="store_true", help="Output JSON report")

    args = parser.parse_args(argv)
    ws = Path(args.workspace).expanduser().resolve()
    if args.cmd == "serve":
        run_server(ws, port=args.port, host_shell=args.host_shell)
        return 0
    if args.cmd == "init":
        return cmd_init(ws)
    if args.cmd == "check":
        return cmd_check(ws, as_json=args.json)
    return 1


if __name__ == "__main__":
    sys.exit(main())
