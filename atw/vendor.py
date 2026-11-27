"""Copy the workbench runtime into a thesis repository, so the thesis carries the exact version it uses.

    python3 -m atw vendor --workspace <thesis>            # into <thesis>/agentic-thesis-workbench/
    python3 -m atw vendor --workspace <thesis> --into tools/atw

Copies atw/, web/, docs/, README.md, LICENSE and thesis.example.toml from the running installation. examples/ and
tests/ stay in the workbench repository. The target folder is replaced as a whole (only that folder), and the
source commit is written to <target>/.source-commit when the installation is a git checkout. The thesis's own
data and rules (thesis.toml, the plan, .thesis/plugins) live outside the target and are never touched.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARTS = ("atw", "web", "docs", "README.md", "LICENSE", "thesis.example.toml")
DEFAULT_DIR = "agentic-thesis-workbench"


def source_commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:
        return ""


def vendor(workspace: Path, into: str = DEFAULT_DIR) -> tuple[Path, str]:
    workspace = workspace.resolve()
    target = (workspace / into).resolve()
    if workspace not in target.parents:
        raise ValueError("the target folder must be inside the thesis repository")
    if target == ROOT:
        raise ValueError("refusing to vendor the workbench onto itself")
    if target.exists():
        marker = target / ".source-commit"
        if any(target.iterdir()) and not marker.exists() and not (target / "atw").is_dir():
            raise ValueError(f"{target} exists and is not a vendored workbench; choose another --into")
        shutil.rmtree(target)
    target.mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
    for part in PARTS:
        src = ROOT / part
        if src.is_dir():
            shutil.copytree(src, target / part, ignore=ignore)
        elif src.is_file():
            shutil.copy2(src, target / part)
    commit = source_commit()
    (target / ".source-commit").write_text((commit or "unknown") + "\n", encoding="utf-8")
    return target, commit
