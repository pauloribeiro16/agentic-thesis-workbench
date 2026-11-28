"""Tasks (work packets for agents) and reviews (their validated outputs).

Cycle: the author creates a task (`atw task new` or the UI) → any agent reads the packet and runs the
role, ideally as a sub-agent → it writes `<reviews_dir>/<TASK>.json` → `atw review validate <TASK>`
checks the schema and the role's permissions, then feeds comments and quality checks.
See docs/SCHEMAS.md for the exact formats.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from .changes import ChangeService
from .comments import CommentService
from .config import WorkbenchConfig
from .formats import get_adapter
from .roles import load_roles, load_workflows

SEVERITIES = ("info", "warn", "bad")
RE_TASK = re.compile(r"^T-\d{3,}$")


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


class TaskService:
    def __init__(self, cfg: WorkbenchConfig) -> None:
        self.cfg = cfg
        self.tdir = cfg.workspace / cfg.tasks_dir
        self.rdir = cfg.workspace / cfg.reviews_dir

    # --- tasks ---
    def _next_id(self) -> str:
        nums = [int(p.stem[2:]) for p in self.tdir.glob("T-*.json") if p.stem[2:].isdigit()] if self.tdir.is_dir() else []
        return f"T-{(max(nums) + 1 if nums else 1):03d}"

    def create(self, role: str | None = None, chapter: int | None = None, workflow: str | None = None,
               comment_ids: list[str] | None = None, note: str = "") -> list[dict[str, Any]]:
        roles, _ = load_roles(self.cfg)
        if workflow:
            flows = load_workflows(self.cfg)
            if workflow not in flows:
                raise ValueError(f"unknown workflow: {workflow}")
            parent = self._write(self._packet(None, chapter, comment_ids, note, workflow=workflow,
                                              children=list(flows[workflow].get("roles", []))))
            out = [parent]
            for r in flows[workflow].get("roles", []):
                if r not in roles:
                    raise ValueError(f"workflow {workflow}: unknown role {r}")
                out.append(self._write(self._packet(roles[r], chapter, comment_ids, note, parent=parent["id"])))
            parent["child_tasks"] = [t["id"] for t in out[1:]]
            self._write(parent)
            return out
        if not role or role not in roles:
            raise ValueError(f"unknown role: {role}")
        return [self._write(self._packet(roles[role], chapter, comment_ids, note))]

    def _packet(self, role, chapter, comment_ids, note, workflow=None, children=None, parent=None) -> dict[str, Any]:
        tid = self._next_id()
        files = [str(p.relative_to(self.cfg.workspace)) for p in get_adapter(self.cfg).sources_for(chapter)] if chapter else []
        packet: dict[str, Any] = {
            "id": tid, "created": _now(), "created_by": self.cfg.moderator_name, "status": "open",
            "chapter": chapter, "files": files, "note": note,
            "inputs": {"style_guide": self.cfg.style_guide_file, "ledger": self.cfg.ledger_file,
                       "dialogue_dir": self.cfg.dialogue_dir, "thesis_toml": "thesis.toml",
                       "plan": self.cfg.plan_file},
            "chapter_plan": self.cfg.spec(chapter) if chapter else {},
            "output": f"{self.cfg.reviews_dir}/{tid}.json",
        }
        if workflow:
            packet.update({"workflow": workflow, "children": children, "role": None,
                           "instructions": "Run each child task (ideally in parallel sub-agents) and validate each one. "
                                           "Optionally write a consolidated review here (kind 'review', role 'consolidator'). "
                                           "This task closes by itself when every child task is valid."})
            return packet
        packet.update({"role": role.id, "role_file": role.path, "writes": role.writes,
                       "independent": role.independent, "fills_check": role.fills_check, "parent": parent})
        if comment_ids is not None or role.writes == "proposals":
            cs = CommentService(self.cfg)
            wanted = set(comment_ids or [])
            packet["comments"] = [
                {k: c.get(k) for k in ("id", "file", "quote", "kind", "text", "replies")}
                for c in (cs.with_anchors(chapter) if chapter else [])
                if (c["id"] in wanted if wanted else c["status"] == "open")
            ]
        if role.writes == "applied" and chapter:
            packet["approved_changes"] = [
                {"comment_id": c["id"], "file": c["file"], "quote": c["proposal"]["quote"],
                 "replacement": c["proposal"]["replacement"]}
                for c in CommentService(self.cfg).approved_changes(chapter)
            ] + [
                {"change_id": it["id"], "file": it["file"], "quote": it.get("old", ""), "replacement": it.get("new", ""),
                 "why": it.get("desc", "")}
                for it in ChangeService(self.cfg).approved_for(set(files))
            ]
        return packet

    def _write(self, packet: dict[str, Any]) -> dict[str, Any]:
        self.tdir.mkdir(parents=True, exist_ok=True)
        (self.cfg.workspace / packet["output"]).parent.mkdir(parents=True, exist_ok=True)
        (self.tdir / f"{packet['id']}.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return packet

    def get(self, tid: str) -> dict[str, Any] | None:
        p = self.tdir / f"{tid}.json"
        return json.loads(p.read_text(encoding="utf-8")) if RE_TASK.match(tid) and p.is_file() else None

    def list(self) -> list[dict[str, Any]]:
        if not self.tdir.is_dir():
            return []
        out = []
        for p in sorted(self.tdir.glob("T-*.json")):
            try:
                t = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            t["has_output"] = (self.cfg.workspace / t["output"]).is_file()
            out.append(t)
        by_id = {t["id"]: t for t in out}
        for t in out:
            kids = [by_id.get(k) for k in t.get("child_tasks", [])]
            if kids and t.get("status") == "open" and all(k and k.get("status") == "done" for k in kids):
                t["status"] = "done"
        return out

    def _set_status(self, tid: str, status: str, errors: list[str]) -> None:
        t = self.get(tid)
        if t:
            t["status"], t["validated"], t["errors"] = status, _now(), errors
            self._write(t)

    # --- reviews ---
    def validate(self, tid: str) -> tuple[bool, list[str]]:
        task = self.get(tid)
        if not task:
            return False, [f"{tid}: task not found"]
        if task.get("status") == "done":  # verify/TaskValidation.tla: an output takes effect once; done is final
            return True, []
        out_path = self.cfg.workspace / task["output"]
        if not out_path.is_file():
            return False, [f"output not written yet: {task['output']}"]
        try:
            doc = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, [f"invalid JSON: {exc}"]
        errors = self._check_doc(task, doc)
        if not errors:
            errors = self._apply_effects(task, doc)
        self._set_status(tid, "done" if not errors else "invalid", errors)
        return not errors, errors

    def _check_doc(self, task: dict[str, Any], doc: dict[str, Any]) -> list[str]:
        e: list[str] = []
        writes = task.get("writes") or "reviews"
        expected = {"reviews": "review", "dialogue": "review", "proposals": "proposals", "applied": "applied"}[writes]
        if doc.get("task") != task["id"]:
            e.append(f"'task' must be {task['id']}")
        if doc.get("kind") != expected:
            e.append(f"'kind' must be '{expected}' for role {task.get('role')}")
        if task.get("role") and doc.get("role") != task["role"]:
            e.append(f"'role' must be {task['role']}")
        ag = doc.get("agent")
        if not isinstance(ag, dict) or not ag.get("name"):
            e.append("'agent' must be an object with at least 'name'")
        if task.get("independent") and doc.get("independent") is not True:
            e.append("independent role: set \"independent\": true (you did not write the reviewed text)")
        files = set(task.get("files") or [])
        if expected == "review":
            if not isinstance(doc.get("summary"), str):
                e.append("'summary' (string) is required")
            for i, f in enumerate(doc.get("findings") or []):
                if f.get("severity") not in SEVERITIES:
                    e.append(f"findings[{i}].severity must be one of {SEVERITIES}")
                if files and f.get("file") not in files:
                    e.append(f"findings[{i}].file is not part of the task")
                if not f.get("problem"):
                    e.append(f"findings[{i}].problem is required")
        elif expected == "proposals":
            for i, p in enumerate(doc.get("proposals") or []):
                if p.get("comment_id") and not task.get("chapter"):
                    e.append(f"proposals[{i}]: answers a comment, but the task has no chapter")
                    continue
                if files and p.get("file") not in files:
                    e.append(f"proposals[{i}].file is not part of the task")
                    continue
                src = self.cfg.workspace / str(p.get("file", ""))
                raw = src.read_text(encoding="utf-8", errors="ignore") if src.is_file() else ""
                if not p.get("quote") or raw.count(p["quote"]) != 1:
                    e.append(f"proposals[{i}].quote must appear exactly once in {p.get('file')}")
                if not isinstance(p.get("replacement"), str):
                    e.append(f"proposals[{i}].replacement is required")
        elif expected == "applied":
            allowed = {c.get("comment_id") or c.get("change_id") for c in task.get("approved_changes", [])}
            for i, a in enumerate(doc.get("applied") or []):
                ref = a.get("comment_id") or a.get("change_id")
                if ref not in allowed:
                    e.append(f"applied[{i}]: {ref} was not an approved change in this task")
        return e

    def _apply_effects(self, task: dict[str, Any], doc: dict[str, Any]) -> list[str]:
        cs = CommentService(self.cfg)
        agent = (doc.get("agent") or {}).get("name", "agent")
        ch = task.get("chapter")
        errors: list[str] = []
        if doc.get("kind") == "proposals":
            for p in doc.get("proposals") or []:
                if p.get("comment_id") and ch:
                    err = cs.set_proposal(ch, p["comment_id"], p, task["id"], agent)
                    if err:
                        errors.append(err)
                elif not p.get("comment_id"):
                    ChangeService(self.cfg).add_proposal(p, task["id"], agent)
        elif doc.get("kind") == "applied":
            for a in doc.get("applied") or []:
                err = (ChangeService(self.cfg).mark_applied(a["change_id"], task["id"], agent) if a.get("change_id")
                       else cs.mark_applied(ch, a["comment_id"], task["id"], agent, a.get("note", "")))
                if err:
                    errors.append(err)
        return errors

    def reviews(self) -> list[dict[str, Any]]:
        out = []
        for t in self.list():
            if not t.get("has_output"):
                continue
            try:
                doc = json.loads((self.cfg.workspace / t["output"]).read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({"task": t, "doc": doc, "valid": t.get("status") == "done",
                        "mtime": (self.cfg.workspace / t["output"]).stat().st_mtime})
        return out

    def valid_reviews(self) -> list[dict[str, Any]]:
        return [r for r in self.reviews() if r["valid"]]
