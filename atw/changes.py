"""Change proposals: concrete before/after edits to the manuscript, decided item by item.

Store: `[agents] proposals_file` (default `.thesis/proposals/proposals.json`)

    {"version": 1,
     "topics": [{"id": "t1", "thread": "CH3_PLAN.md", "q": "Q1", "title": "...", "why": "..."}],
     "items":  [{"id": "P-1a2b3c", "topic": "t1", "file": "chapters/03.md", "old": "...", "new": "...",
                 "desc": "...", "status": "pending|approved|rejected|applied", "decision": "kept|contested",
                 "parent": null, "registered": null, "by": "...", "task": "T-012", "seal": "<hmac>"}]}

Verdict (one rule for the manuscript, the queue and the checks):
    pending | approved | rejected — not yet in the text;
    applied + no author decision  → review (in the text without the author's approval);
    applied + kept / contested    → approved / rejected.
The workbench never edits the chapter: an implementer applies approved, sealed changes. Approving seals the
item with the author's key, so editing the JSON does not approve anything. Decisions can be registered in the
dialogue thread of their topic as a sealed moderator block.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from .comments import _norm, plain_map
from .config import WorkbenchConfig
from .dialogue import DialogueService, ModeratorSeal

_LOCK = threading.Lock()
KEEP = {"kept": "approved", "aprovada": "approved", "contested": "rejected", "contestada": "rejected"}


def verdict(it: dict[str, Any]) -> str:
    if it.get("status") == "applied":
        return KEEP.get(str(it.get("decision")), "review")
    return str(it.get("status") or "pending")


def _today() -> str:
    return dt.date.today().isoformat()


class ChangeService:
    def __init__(self, cfg: WorkbenchConfig) -> None:
        self.cfg = cfg
        self.path = cfg.workspace / cfg.proposals_file
        self.seal = ModeratorSeal(cfg)
        self.pt = cfg.dialogue_profile == "pt-legacy"

    # --- storage ---
    def _read(self) -> dict[str, Any]:
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    data = {"version": 1, "topics": [], "items": data}
                data.setdefault("topics", [])
                data.setdefault("items", [])
                return data
            except Exception:
                pass
        return {"version": 1, "topics": [], "items": []}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".proposals.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    @staticmethod
    def _payload(it: dict[str, Any]) -> str:
        return json.dumps(["change", it.get("id"), it.get("file"), it.get("old"), it.get("new")], ensure_ascii=False)

    def sealed(self, it: dict[str, Any]) -> bool:
        return bool(it.get("seal")) and self.seal.verify_payload(self._payload(it), it["seal"])

    # --- reading ---
    def load(self, chapter_files: dict[str, int] | None = None) -> dict[str, Any]:
        """All items with verdict, anchor in the current text and chapter number (when the file is known)."""
        data = self._read()
        topics = {t.get("id"): t for t in data["topics"]}
        cache: dict[str, str] = {}
        out = []
        for raw in data["items"]:
            it = dict(raw)
            rel = it.get("file", "")
            if rel not in cache:
                p = (self.cfg.workspace / rel).resolve()
                cache[rel] = p.read_text(encoding="utf-8", errors="ignore") \
                    if self.cfg.workspace in p.parents and p.is_file() else ""
            text = cache[rel]
            it["verdict"] = verdict(it)
            needle = it.get("new", "") if it.get("status") == "applied" else it.get("old", "")
            n = text.count(needle) if needle else 0
            it["anchor"] = {"state": "exact" if n == 1 else "missing" if n == 0 else "ambiguous",
                            "pos": text.find(needle) if n >= 1 else -1,
                            "plain": _norm(plain_map(needle)[0]) if needle else ""}
            t = topics.get(it.get("topic"), {})
            it["thread"], it["q"], it["topic_title"] = t.get("thread", ""), t.get("q", ""), t.get("title", "")
            it["sealed"] = self.sealed(it) if it.get("status") == "approved" else False
            if chapter_files is not None:
                it["chapter"] = chapter_files.get(rel)
            out.append(it)
        return {"topics": data["topics"], "items": out}

    def counts(self, items: list[dict[str, Any]] | None = None) -> dict[str, int]:
        items = items if items is not None else self.load()["items"]
        top = [i for i in items if not i.get("parent")]
        c = {k: sum(1 for i in top if i["verdict"] == k) for k in ("pending", "review", "approved", "rejected")}
        c["to_register"] = sum(1 for i in top if i["verdict"] in ("approved", "rejected") and not i.get("registered"))
        c["to_apply"] = sum(1 for i in top if i.get("status") == "approved")
        return c

    # --- author actions ---
    def apply(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        action = payload.get("action")
        ids = payload.get("ids")
        with _LOCK:
            data = self._read()
            if action == "register":
                return self._register(data, bool(payload.get("preview")))
            if not isinstance(ids, list) or not ids:
                return 400, {"error": "no ids"}
            items = {it.get("id"): it for it in data["items"]}
            missing = [i for i in ids if i not in items]
            if missing:
                return 404, {"error": f"change not found: {missing[0]}"}
            targets = [it for it in data["items"] if it.get("id") in ids or it.get("parent") in ids]
            if any(it.get("registered") for it in targets):
                return 409, {"error": "already registered in the dialogue"}
            if action == "decide":
                decision = payload.get("decision")
                if decision not in ("pending", "approved", "rejected"):
                    return 400, {"error": "invalid decision"}
                if any(it.get("status") == "applied" for it in targets):
                    return 409, {"error": "already in the text — use review"}
                for it in targets:
                    it["status"] = decision
                    it["decided_by"], it["decided_at"] = self.cfg.moderator_name, _today()
                    if decision == "approved":
                        it["seal"] = self.seal.sign_payload(self._payload(it))
                    else:
                        it.pop("seal", None)
            elif action == "review":
                decision = payload.get("decision")
                if decision not in ("kept", "contested", "undo"):
                    return 400, {"error": "invalid review decision"}
                if any(it.get("status") != "applied" for it in targets):
                    return 409, {"error": "not in the text yet"}
                word = {"kept": "aprovada", "contested": "contestada"} if self.pt else {"kept": "kept", "contested": "contested"}
                for it in targets:
                    if decision == "undo":
                        if "decision_before" in it:
                            it["decision"] = it.pop("decision_before")
                    else:
                        it.setdefault("decision_before", it.get("decision"))
                        it["decision"] = word[decision]
            else:
                return 400, {"error": "invalid action"}
            self._save(data)
            return 200, {"ok": True}

    def _register(self, data: dict[str, Any], preview: bool) -> tuple[int, dict[str, Any]]:
        topics = {t.get("id"): t for t in data["topics"]}
        groups: dict[str, dict[str, Any]] = {}
        for it in data["items"]:
            v = verdict(it)
            if v not in ("approved", "rejected") or it.get("registered"):
                continue
            t = topics.get(it.get("topic"), {})
            thread = t.get("thread") or ""
            if not thread:
                continue
            g = groups.setdefault(thread, {"items": [], "qs": {}})
            g["items"].append(it)
            if it.get("parent"):
                continue
            slot = g["qs"].setdefault(t.get("q") or t.get("title") or "-", {"approved": [], "rejected": [], "contested": []})
            kind = "approved" if v == "approved" else "contested" if it.get("status") == "applied" else "rejected"
            slot[kind].append(it["id"])
        if not groups:
            return 400, {"error": "nothing new to register"}
        names = ({"approved": "aprovadas", "rejected": "rejeitadas", "contested": "já no texto, com reversão pedida"}
                 if self.pt else {"approved": "approved", "rejected": "rejected", "contested": "in the text, reversal requested"})
        head = (f"Decisões item a item (`{self.cfg.proposals_file}`)." if self.pt
                else f"Item-by-item decisions (`{self.cfg.proposals_file}`).")
        dlg = DialogueService(self.cfg)
        previews: dict[str, str] = {}
        for thread, g in groups.items():
            lines = [head, ""]
            for q, st in g["qs"].items():
                parts = [f"{names[k]} " + ", ".join(v) for k, v in st.items() if v]
                lines.append(f"- `{q}`: " + "; ".join(parts) + ".")
            if preview:
                previews[thread] = "\n".join(lines)
                continue
            ok, msg = dlg.append_message(thread, lines)
            if not ok:
                return 400, {"error": f"{thread}: {msg}"}
            for it in g["items"]:
                it["registered"] = _today()
            self._save(data)  # per thread: a failure later does not repeat a block already written
        return 200, {"ok": True, "preview": previews} if preview else {"ok": True, "threads": list(groups)}

    # --- agent side (through validated task outputs) ---
    def add_proposal(self, p: dict[str, Any], task: str, agent: str) -> str:
        with _LOCK:
            data = self._read()
            cid = "P-" + uuid.uuid4().hex[:6]
            data["items"].append({"id": cid, "topic": p.get("topic", ""), "file": p["file"], "old": p["quote"],
                                  "new": p["replacement"], "desc": p.get("rationale", ""), "status": "pending",
                                  "by": agent, "task": task})
            self._save(data)
        return cid

    def approved_for(self, files: set[str]) -> list[dict[str, Any]]:
        return [it for it in self._read()["items"]
                if it.get("status") == "approved" and it.get("file") in files and self.sealed(it)]

    def mark_applied(self, cid: str, task: str, agent: str) -> str | None:
        with _LOCK:
            data = self._read()
            it = next((x for x in data["items"] if x.get("id") == cid), None)
            if it is None:
                return f"{cid}: change not found"
            if it.get("status") != "approved" or not self.sealed(it):
                return f"{cid}: change is not approved and sealed by the author"
            src = self.cfg.workspace / it["file"]
            raw = src.read_text(encoding="utf-8", errors="ignore") if src.is_file() else ""
            if it.get("new") and it["new"] not in raw:
                return f"{cid}: the approved text is not in {it['file']}"
            it["status"] = "applied"
            it["decision"] = "aprovada" if self.pt else "kept"
            it["applied"], it["applied_by"], it["task"] = _today(), agent, task
            self._save(data)
        return None
