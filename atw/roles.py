"""Agent roles (templates for sub-agents) and workflows (roles run together).

A role lives in `<roles dir>/<id>/ROLE.md`: YAML-like front matter compatible with the Agent Skills
`SKILL.md` header (`name`, `description`) plus workbench fields, followed by the instructions.

    ---
    name: tone-reviewer
    description: Audits register and tone of one chapter against the style guide.
    writes: reviews            # reviews | proposals | applied | dialogue — never chapter files
    independent: true          # must not review text it wrote
    fills_check: tone          # quality check fed by this role's reviews
    inputs: [chapter, style_guide]
    tools: [read]
    ---
    <instructions>

Sources (later override earlier): built-in `atw/roles/`, installed packages exposing entry-point group
`atw.roles` (a module next to a `roles/` folder), and the workspace `roles_dirs` (default `.thesis/roles`).
Workflows: built-in `atw/roles/workflows.toml` plus `[[workflows]]` in thesis.toml.
"""
from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any

from .config import WorkbenchConfig

BUILTIN_DIR = Path(__file__).resolve().parent / "roles"
WRITES = {"reviews", "proposals", "applied", "dialogue"}


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Minimal YAML subset: `key: value`, `key: [a, b]`, booleans, integers, quoted strings, # comments."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta: dict[str, Any] = {}
    for line in text[3:end].splitlines():
        line = re.sub(r"\s+#.*$", "", line).rstrip()
        if not line.strip() or ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = _scalar(v.strip())
    return meta, text[end + 4:].lstrip("\n")


def _scalar(v: str) -> Any:
    if v.startswith("[") and v.endswith("]"):
        return [_scalar(x.strip()) for x in v[1:-1].split(",") if x.strip()]
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


@dataclass
class Role:
    id: str
    description: str
    instructions: str
    writes: str = "reviews"
    independent: bool = True
    fills_check: str = ""
    inputs: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    source: str = "builtin"
    path: str = ""

    def public(self, with_instructions: bool = False) -> dict[str, Any]:
        d = {"id": self.id, "description": self.description, "writes": self.writes,
             "independent": self.independent, "fills_check": self.fills_check, "inputs": self.inputs,
             "tools": self.tools, "source": self.source, "path": self.path}
        if with_instructions:
            d["instructions"] = self.instructions
        return d


def _load_dir(root: Path, source: str, out: dict[str, Role], errors: list[str]) -> None:
    if not root.is_dir():
        return
    for f in sorted(root.glob("*/ROLE.md")):
        try:
            meta, body = parse_front_matter(f.read_text(encoding="utf-8"))
            rid = str(meta.get("name") or f.parent.name)
            writes = str(meta.get("writes", "reviews"))
            if writes not in WRITES:
                raise ValueError(f"writes must be one of {sorted(WRITES)}")
            out[rid] = Role(rid, str(meta.get("description", "")), body.strip(), writes,
                            bool(meta.get("independent", True)), str(meta.get("fills_check", "")),
                            list(meta.get("inputs", []) or []), list(meta.get("tools", []) or []), source, str(f))
        except Exception as exc:
            errors.append(f"{f}: {exc}")


def load_roles(cfg: WorkbenchConfig) -> tuple[dict[str, Role], list[str]]:
    roles: dict[str, Role] = {}
    errors: list[str] = []
    _load_dir(BUILTIN_DIR, "builtin", roles, errors)
    try:
        eps = metadata.entry_points(group="atw.roles")
    except Exception:
        eps = []
    for ep in eps:
        try:
            mod = ep.load()
            _load_dir(Path(mod.__file__).resolve().parent / "roles", f"package:{ep.value}", roles, errors)
        except Exception as exc:
            errors.append(f"{ep.name}: {exc}")
    for d in cfg.roles_dirs:
        _load_dir(cfg.workspace / d, f"workspace:{d}", roles, errors)
    return roles, errors


def load_workflows(cfg: WorkbenchConfig) -> dict[str, dict[str, Any]]:
    flows: dict[str, dict[str, Any]] = {}
    wf = BUILTIN_DIR / "workflows.toml"
    if wf.is_file():
        for w in tomllib.loads(wf.read_text(encoding="utf-8")).get("workflows", []):
            flows[w["id"]] = {**w, "source": "builtin"}
    for w in cfg.raw.get("workflows", []) if isinstance(cfg.raw.get("workflows"), list) else []:
        if "id" in w:
            flows[w["id"]] = {**w, "source": "workspace"}
    return flows


# --- export to agent tools -----------------------------------------------------------------------

def contract_text(role: Role, cfg: WorkbenchConfig) -> str:
    out_kind = {"reviews": "review", "proposals": "proposals", "applied": "applied", "dialogue": "review"}[role.writes]
    return f"""

## Workbench contract (generated — do not edit here)

- You receive a task packet: `{cfg.tasks_dir}/<TASK>.json`. Read it first; it lists the chapter files,
  inputs and the exact output path.
- Write **only** the output file named in the packet (`{cfg.reviews_dir}/<TASK>.json`), as JSON with
  `"kind": "{out_kind}"` following `docs/SCHEMAS.md`. Never edit chapter files{' except to apply approved, sealed changes listed in the packet' if role.writes == 'applied' else ''}.
- Identify yourself in `"agent": {{"name": ..., "model": ...}}`.{' You must not review text you wrote yourself; set `"independent": true`.' if role.independent else ''}
- When done, run `python3 -m atw review validate <TASK> --workspace <thesis>` and fix any error it reports.
"""


def export_roles(cfg: WorkbenchConfig, target: str, dest: str | None = None) -> list[Path]:
    """target: claude (.claude/agents/<id>.md) | skills (Agent Skills SKILL.md folders) | markdown (plain prompts)."""
    roles, _ = load_roles(cfg)
    written: list[Path] = []
    base = cfg.workspace / (dest or {"claude": ".claude/agents", "skills": ".agents/skills",
                                     "markdown": ".thesis/prompts"}[target])
    for r in roles.values():
        body = r.instructions + contract_text(r, cfg)
        desc = r.description.replace("\n", " ")
        if target == "claude":
            tools = "Read, Bash, Write" if r.writes != "dialogue" else "Read, Bash, Edit, Write"
            p = base / f"{r.id}.md"
            text = f"---\nname: {r.id}\ndescription: {desc}\ntools: {tools}\n---\n\n{body}\n"
        elif target == "skills":
            p = base / r.id / "SKILL.md"
            text = f"---\nname: {r.id}\ndescription: {json.dumps(desc)}\n---\n\n{body}\n"
        else:
            p = base / f"{r.id}.md"
            text = f"# Role: {r.id}\n\n{desc}\n\n{body}\n"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        written.append(p)
    return written
