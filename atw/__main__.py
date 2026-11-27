"""CLI for Agentic Thesis Workbench (`python3 -m atw ...`)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import load_config

DEFAULT_TOML = """[project]
title = "{title}"
author = "Your Name"
language = "en-GB"
plan = ".thesis/plan.toml"           # YOUR targets, chapters and writing rules (not engine defaults)

[ui]
locale = "en"                        # en | pt  (interface only)

[format]
adapter = "markdown"                 # markdown | markdown-latex | quarto | latex | <plugin id>
chapters_glob = "chapters/*.md"
# compile_command = ["tectonic", "latex/ch{{chapter}}.tex"]
# [format.pages]
# limit = 25
# pdf = "latex/ch{{chapter}}.pdf"

[citations]
provider = "bibtex"                  # bibtex | csl-json | <plugin id>
bib_file = "references.bib"
syntax = "author-year"               # author-year | pandoc | latex
ledger_file = ".thesis/citations/ledger.json"

[agents]
moderator_name = "Your Name"
sign_decisions = true

[quality]
packs = ["core", "citations", "style", "governance", "agent-review"]
forbid_first_person = false
spelling_variant = "en-GB"           # none | en-GB | en-US
"""

SERVE_SH = """#!/bin/sh
# Open the workbench for this thesis. Uses a vendored copy in agentic-thesis-workbench/ when present
# (python3 -m atw vendor --workspace .), otherwise the installed one.
cd "$(dirname "$0")/.."
[ -d agentic-thesis-workbench/atw ] && export PYTHONPATH=agentic-thesis-workbench
exec python3 -m atw serve --workspace . --port "${1:-8765}"
"""

GITIGNORE = [".thesis/build/", ".thesis/pages.json", "__pycache__/"]

PLAN_TOML = """# Your plan for this thesis — these are your choices, not engine defaults.
# Delete or change anything. A check whose rule is not set here reports "not configured".

# [chapter_defaults]
# pages = [20, 25]          # pages per chapter, without references or in-text citations
# words = [6000, 7500]      # reference only; pages decide
# sections = 5

# [[chapters]]
# number = 1
# title = "Introduction"
# pages = [8, 12]
# narrative = "What this chapter must argue, in one or two sentences."

# [quality]
# max_sentence_words = 40
# forbid_first_person = true
# prohibited_phrases = []
# emphasis_words = []
"""

AGENTS_MD = """# AGENTS.md — how agents work in this thesis

This thesis uses Agentic Thesis Workbench. Read `docs/AGENT_MANUAL.md` in the workbench repository.

1. **Never edit chapter files** unless you are running the `implementer` role on changes the author approved and sealed.
2. **Work through tasks.** When asked to "do T-007", read `{tasks_dir}/T-007.json`, load the role it names
   (`python3 -m atw roles show <role>`), run it — as a sub-agent if your tool supports one — and write the output
   named in the packet. Then run `python3 -m atw review validate T-007 --workspace .`.
3. **Dialogue is append-only** in `{dialogue_dir}/`: `## Turn N — <Agent> (<Model>) — YYYY-MM-DD`, then
   `**Qn — Title**` and a verdict (`AGREE`, `PARTIALLY AGREE`, `DISAGREE`). Agents propose states; only the author's
   sealed decision approves.
4. **Cite only verified passages** (ledger: `{ledger_file}`).
5. **Change rules through configuration** (`thesis.toml`, style guide, plugins in `.thesis/plugins/`), never in the engine.
"""


def cmd_init(workspace: Path) -> int:
    workspace.mkdir(parents=True, exist_ok=True)
    toml_path = workspace / "thesis.toml"
    if not toml_path.exists():
        toml_path.write_text(DEFAULT_TOML.format(title=workspace.name), encoding="utf-8")
        print(f"Created {toml_path}")
    cfg = load_config(workspace)
    for rel in (cfg.dialogue_dir, cfg.comments_dir, cfg.tasks_dir, cfg.reviews_dir, cfg.plugin_dirs[0],
                Path(cfg.ledger_file).parent, Path(cfg.style_guide_file).parent):
        (workspace / rel).mkdir(parents=True, exist_ok=True)
    plan = workspace / ".thesis" / "plan.toml"
    if not plan.exists():
        plan.write_text(PLAN_TOML, encoding="utf-8")
        print(f"Created {plan}")
    guide = workspace / cfg.style_guide_file
    if not guide.exists():
        guide.write_text(json.dumps({"version": 1, "entries": []}, indent=2) + "\n", encoding="utf-8")
        print(f"Created {guide}")
    serve = workspace / ".thesis" / "serve.sh"
    if not serve.exists():
        serve.write_text(SERVE_SH, encoding="utf-8")
        print(f"Created {serve}")
    gi = workspace / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    missing = [l for l in GITIGNORE if l not in lines]
    if missing:
        with gi.open("a", encoding="utf-8") as fh:
            fh.write(("\n" if lines else "") + "# Agentic Thesis Workbench: local builds and measurements\n" + "\n".join(missing) + "\n")
        print(f"Updated {gi}")
    agents_md = workspace / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text(AGENTS_MD.format(tasks_dir=cfg.tasks_dir, dialogue_dir=cfg.dialogue_dir,
                                              ledger_file=cfg.ledger_file), encoding="utf-8")
        print(f"Created {agents_md}")
    print("Workspace ready. Run: python3 -m atw serve --workspace", workspace)
    return 0


def cmd_check(workspace: Path, as_json: bool, chapter: int | None) -> int:
    from .quality import run_quality_checks
    report = run_quality_checks(load_config(workspace), only_chapter=chapter)
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    for e in report["plugin_errors"]:
        print(f"! plugin: {e}")
    for ch in report["chapters"]:
        s = ch["summary"]
        print(f"Chapter {ch['chapter']:02d} {ch['title']} — {ch['words']} words | bad={s['bad']} warn={s['warn']} "
              f"review={s['na']} error={s['error']}")
        for c in ch["checks"]:
            if c["state"] in ("bad", "warn", "error"):
                print(f"   [{c['state']:5}] {c['id']:<18} {c['count']:>4}  {c['label']}")
    for c in report["thesis_checks"]:
        if c["state"] != "ok":
            print(f"[{c['state']:5}] {c['id']:<18} {c['count']:>4}  {c['label']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="atw", description="Agentic Thesis Workbench")
    sub = p.add_subparsers(dest="cmd", required=True)

    def ws(sp):
        sp.add_argument("--workspace", default=".", help="path to the thesis repository")
        return sp

    s = ws(sub.add_parser("serve", help="start the local web workbench"))
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--host-shell", default=os.environ.get("HOST_SHELL", "standalone"), choices=("standalone", "second-brain"))
    ws(sub.add_parser("init", help="create thesis.toml, .thesis/ and AGENTS.md"))
    c = ws(sub.add_parser("check", help="run the quality checks"))
    c.add_argument("--json", action="store_true")
    c.add_argument("--chapter", type=int)

    t = sub.add_parser("task", help="create and inspect tasks for agents").add_subparsers(dest="sub", required=True)
    tn = ws(t.add_parser("new"))
    g = tn.add_mutually_exclusive_group(required=True)
    g.add_argument("--role")
    g.add_argument("--workflow")
    tn.add_argument("--chapter", type=int)
    tn.add_argument("--comments", help="comma-separated comment ids")
    tn.add_argument("--note", default="")
    ws(t.add_parser("list"))
    ts = ws(t.add_parser("show"))
    ts.add_argument("id")

    r = sub.add_parser("review", help="validate agent outputs").add_subparsers(dest="sub", required=True)
    rv = ws(r.add_parser("validate"))
    rv.add_argument("id")

    ro = sub.add_parser("roles", help="list, show and export agent roles").add_subparsers(dest="sub", required=True)
    ws(ro.add_parser("list"))
    rs = ws(ro.add_parser("show"))
    rs.add_argument("id")
    re_ = ws(ro.add_parser("export"))
    re_.add_argument("--to", choices=("claude", "skills", "markdown"), required=True)
    re_.add_argument("--dest", help="destination folder relative to the workspace")

    ws(sub.add_parser("plugins", help="list loaded plugins and checks"))
    v = ws(sub.add_parser("vendor", help="copy this workbench into a thesis repository (exact version, no examples/tests)"))
    v.add_argument("--into", default="agentic-thesis-workbench", help="folder inside the thesis")
    k = sub.add_parser("key", help="signing key for the author's approvals").add_subparsers(dest="sub", required=True)
    ws(k.add_parser("status"))
    ws(k.add_parser("init"))

    a = p.parse_args(argv)
    w = Path(a.workspace).expanduser().resolve()
    if a.cmd == "serve":
        from .server import run_server
        run_server(w, port=a.port, host_shell=a.host_shell)
        return 0
    if a.cmd == "init":
        return cmd_init(w)
    if a.cmd == "check":
        return cmd_check(w, a.json, a.chapter)
    cfg = load_config(w)
    if a.cmd == "task":
        from .tasks import TaskService
        svc = TaskService(cfg)
        if a.sub == "new":
            ids = [x.strip() for x in a.comments.split(",")] if a.comments else None
            try:
                for task in svc.create(role=a.role, workflow=a.workflow, chapter=a.chapter, comment_ids=ids, note=a.note):
                    print(f"{task['id']}  {task.get('role') or 'workflow:' + task.get('workflow', '')}  → {task['output']}")
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        elif a.sub == "list":
            for task in svc.list():
                print(f"{task['id']}  {task.get('status'):8} ch={task.get('chapter')}  {task.get('role') or task.get('workflow')}")
        else:
            task = svc.get(a.id)
            print(json.dumps(task, indent=2, ensure_ascii=False) if task else f"{a.id}: not found")
        return 0
    if a.cmd == "review":
        from .tasks import TaskService
        ok, errors = TaskService(cfg).validate(a.id)
        print("valid" if ok else "invalid:\n- " + "\n- ".join(errors))
        return 0 if ok else 1
    if a.cmd == "roles":
        from .roles import export_roles, load_roles
        roles, errors = load_roles(cfg)
        if a.sub == "list":
            for role in roles.values():
                print(f"{role.id:<20} writes={role.writes:<9} {role.description}")
            for e in errors:
                print(f"! {e}")
        elif a.sub == "show":
            role = roles.get(a.id)
            if not role:
                print(f"{a.id}: not found", file=sys.stderr)
                return 2
            from .roles import contract_text
            print(role.instructions + contract_text(role, cfg))
        else:
            for path in export_roles(cfg, a.to, a.dest):
                print(f"wrote {path}")
        return 0
    if a.cmd == "vendor":
        from .vendor import vendor
        try:
            target, commit = vendor(w, a.into)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"{target} = {commit or 'unknown commit'}")
        print(f"Run it with: PYTHONPATH={a.into} python3 -m atw serve --workspace .")
        return 0
    if a.cmd == "key":
        from .dialogue import ModeratorSeal
        seal = ModeratorSeal(cfg)
        st = seal.status()
        if a.sub == "init":
            if st["key_exists"]:
                print(f"A key already exists at {st['key_path']} — nothing changed.")
            else:
                print(f"Created {seal.create_key()} (keep it outside the repository; back it up).")
            return 0
        print(f"signing {'on' if st['enabled'] else 'off'} · key {st['key_path']} · {'exists' if st['key_exists'] else 'MISSING'}")
        return 0 if st["key_exists"] or not st["enabled"] else 1
    if a.cmd == "plugins":
        from .plugins import load_registry
        reg = load_registry(cfg)
        for pl in reg.plugins:
            print(f"{pl['id']:<24} {pl['version']:<6} {pl['source']}")
        print(f"\nchecks ({len(reg.checks)}): " + ", ".join(sorted(reg.checks)))
        print("formats: " + ", ".join(sorted(reg.formats)) + " · citations: " + ", ".join(sorted(reg.citation_providers)))
        for e in reg.errors:
            print(f"! {e}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
