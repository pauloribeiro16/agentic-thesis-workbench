"""Anchored comments on the manuscript, with a closing workflow.

Comments live in `<comments_dir>/CH<n>.json`, never inside the chapter files. Each one stores the exact
quoted text plus a little context (`prefix`, `suffix`) and a position hint (`pos`), following the W3C
Web Annotation TextQuote/TextPosition selectors. When the text changes, the anchor is found again by
exact match (disambiguated by context and position) or by fuzzy match; otherwise it becomes an orphan.

Lifecycle:
    open ──agent proposal──▶ addressed ──author accepts──▶ approved ──implementer applies──▶ applied
      ▲                          │                                                            │
      └──── author reopens ◀─────┘                                     author confirms ──▶ resolved
    (any non-final state) ── author ──▶ wontfix
An author's own suggestion (kind "suggest") is approved on creation. Approvals are HMAC-sealed, so an
agent cannot approve a change by editing the JSON.
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import os
import re
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from .config import WorkbenchConfig
from .dialogue import ModeratorSeal
from .formats import get_adapter

KINDS = ("fix", "question", "cite", "style", "suggest", "note")
STATES = ("open", "addressed", "approved", "applied", "resolved", "wontfix")
TO_CLOSE = ("addressed", "applied")
MAX_TEXT, MAX_QUOTE, MAX_CONTEXT = 5000, 4000, 200
_LOCK = threading.Lock()
RE_MD_LINE = re.compile(r"^(\s*(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s*))")


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def plain_map(raw: str) -> tuple[str, list[int]]:
    """Plain text as rendered (inline Markdown markers, line markers and table pipes removed,
    whitespace collapsed) and, for each plain character, its index in `raw`."""
    out: list[str] = []
    idx: list[int] = []
    pos = 0
    for line in raw.splitlines(keepends=True):
        m = RE_MD_LINE.match(line)
        start = m.end() if m else 0
        is_sep = bool(re.fullmatch(r"\s*\|[\s:|-]+\|\s*\n?", line))
        for j, c in enumerate(line):
            if j < start or is_sep or c in "*`|" :
                continue
            if c.isspace():
                if out and out[-1] != " ":
                    out.append(" ")
                    idx.append(pos + j)
                continue
            out.append(c)
            idx.append(pos + j)
        pos += len(line)
    text = "".join(out)
    return text, idx


def _norm(s: str) -> str:
    return " ".join(s.replace("*", "").replace("`", "").replace("|", " ").split())


def locate(raw: str, c: dict[str, Any]) -> dict[str, Any]:
    """Find the comment's anchor in the current raw text. Returns {state, start, end, plain}."""
    quote = c.get("quote", "")
    if not quote:
        return {"state": "orphan"}
    hits = [m.start() for m in re.finditer(re.escape(quote), raw)]
    if hits:
        pre, suf, pos = c.get("prefix", ""), c.get("suffix", ""), c.get("pos")

        def score(h: int) -> tuple:
            ctx_ok = (raw[max(0, h - len(pre)):h].endswith(pre) if pre else True) + \
                     (raw[h + len(quote):h + len(quote) + len(suf)].startswith(suf) if suf else True)
            return (-ctx_ok, abs(h - pos) if isinstance(pos, int) else 0)
        h = min(hits, key=score)
        return {"state": "exact", "start": h, "end": h + len(quote), "plain": _norm(plain_map(quote)[0])}
    # fuzzy: anchor on the longest common block, then compare a window of the quote's length
    sm = difflib.SequenceMatcher(None, quote, raw, autojunk=False)
    m = sm.find_longest_match(0, len(quote), 0, len(raw))
    if m.size >= min(20, max(8, len(quote) // 4)):
        start = max(0, m.b - m.a)
        end = min(len(raw), start + len(quote))
        cand = raw[start:end]
        ratio = difflib.SequenceMatcher(None, quote, cand, autojunk=False).ratio()
        if ratio >= 0.75:
            return {"state": "fuzzy", "start": start, "end": end, "plain": _norm(plain_map(cand)[0]), "ratio": round(ratio, 2)}
    return {"state": "orphan"}


def text_shows(raw: str, old: str, new: str) -> bool:
    """The file shows an approved change: the replacement is there and the replaced passage is gone (unless the
    passage is part of the replacement). Covers deletions, where the empty replacement is trivially "there".
    Proved in verify/CommentLifecycle.tla (AppliedMeansEdited)."""
    return (not new or new in raw) and (not old or old in new or old not in raw)


class CommentService:
    def __init__(self, cfg: WorkbenchConfig) -> None:
        self.cfg = cfg
        self.seal = ModeratorSeal(cfg)

    # --- storage ---
    def _path(self, ch: int) -> Path:
        return self.cfg.workspace / self.cfg.comments_dir / f"CH{ch}.json"

    def load(self, ch: int) -> dict[str, Any]:
        p = self._path(ch)
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    data = {"version": 1, "chapter": ch, "comments": data}
                return data
            except Exception:
                pass
        return {"version": 1, "chapter": ch, "comments": []}

    def _save(self, ch: int, data: dict[str, Any]) -> None:
        p = self._path(ch)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".comments.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp, p)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def chapters_with_comments(self) -> list[int]:
        d = self.cfg.workspace / self.cfg.comments_dir
        return sorted(int(m.group(1)) for p in d.glob("CH*.json") if (m := re.fullmatch(r"CH(\d+)\.json", p.name))) if d.is_dir() else []

    def _chapter_files(self, ch: int) -> dict[str, str]:
        ws = self.cfg.workspace
        return {str(p.relative_to(ws)): p.read_text(encoding="utf-8", errors="ignore")
                for p in get_adapter(self.cfg).sources_for(ch)}

    # --- reading ---
    def with_anchors(self, ch: int) -> list[dict[str, Any]]:
        files = self._chapter_files(ch)
        out = []
        for c in self.load(ch).get("comments", []):
            c = dict(c)
            c["status"] = c.get("status") if c.get("status") in STATES else "open"
            c.setdefault("kind", "note")
            c.setdefault("replies", [])
            c["anchor"] = locate(files[c["file"]], c) if c.get("file") in files else {"state": "orphan"}
            if c.get("proposal"):
                c["proposal"]["sealed"] = self._proposal_sealed(c)
            out.append(c)
        return out

    def queue(self) -> dict[str, Any]:
        """Everything waiting for the author to close, across chapters."""
        items: list[dict[str, Any]] = []
        counts = {s: 0 for s in STATES}
        for ch in self.chapters_with_comments():
            for c in self.with_anchors(ch):
                counts[c["status"]] += 1
                if c["status"] in TO_CLOSE:
                    items.append({**c, "chapter": ch})
        items.sort(key=lambda c: (c["status"] != "addressed", c["chapter"], c.get("file", ""), c.get("pos") or 0))
        return {"items": items, "counts": counts}

    # --- seals ---
    @staticmethod
    def _payload(c: dict[str, Any]) -> str:
        p = c.get("proposal") or {}
        return json.dumps([c.get("id"), c.get("file"), p.get("quote"), p.get("replacement")], ensure_ascii=False)

    def _proposal_sealed(self, c: dict[str, Any]) -> bool:
        p = c.get("proposal") or {}
        return bool(p.get("approved_at")) and self.seal.verify_payload(self._payload(c), p.get("seal", ""))

    # --- writing (UI actions are the author's; agents use set_proposal / mark_applied via validated reviews) ---
    def apply(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            ch = int(payload.get("ch"))
        except (TypeError, ValueError):
            return 400, {"error": "invalid chapter"}
        action = payload.get("action")
        author = self.cfg.moderator_name
        with _LOCK:
            data = self.load(ch)
            items = data.setdefault("comments", [])
            if action == "add":
                return self._add(ch, data, items, payload, author)
            c = next((x for x in items if x.get("id") == payload.get("id")), None)
            if c is None:
                return 404, {"error": "comment not found"}
            hist = c.setdefault("history", [])
            if action == "reply":
                text = str(payload.get("text") or "").strip()[:MAX_TEXT]
                if not text:
                    return 400, {"error": "empty reply"}
                c.setdefault("replies", []).append({"author": author, "date": _now(), "text": text})
            elif action == "status":
                st = payload.get("status")
                if st not in ("open", "resolved", "wontfix"):
                    return 400, {"error": "the author may set open, resolved or wontfix"}
                if st == "open" and payload.get("text"):
                    c.setdefault("replies", []).append({"author": author, "date": _now(), "text": str(payload["text"])[:MAX_TEXT]})
                c["status"] = st
                hist.append({"date": _now(), "by": author, "status": st})
            elif action == "accept":
                if c.get("status") != "addressed" or not c.get("proposal"):
                    return 409, {"error": "nothing to accept"}
                src = self.cfg.workspace / str(c.get("file", ""))
                raw = src.read_text(encoding="utf-8", errors="ignore") if src.is_file() else ""
                pq = c["proposal"].get("quote", "")
                if not pq or raw.count(pq) != 1:  # verify/CommentLifecycle.tla: accept needs an anchored proposal
                    return 409, {"error": "the proposal's passage is not in the text exactly once — ask for a new proposal"}
                self._approve(c, author)
                hist.append({"date": _now(), "by": author, "status": "approved"})
            elif action == "reattach":
                anchor, err = self._anchor(ch, payload)
                if err:
                    return 400, {"error": err}
                c.update(anchor)
            elif action == "delete":
                if c.get("author") != author:
                    return 403, {"error": "only your own comments can be deleted; mark it resolved instead"}
                items.remove(c)
            else:
                return 400, {"error": "invalid action"}
            self._save(ch, data)
            return 200, {"ok": True}

    def _approve(self, c: dict[str, Any], author: str) -> None:
        c["proposal"]["approved_by"] = author
        c["proposal"]["approved_at"] = _now()
        c["proposal"]["seal"] = self.seal.sign_payload(self._payload(c))
        c["status"] = "approved"

    def _anchor(self, ch: int, payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        """Anchor a selection made on the rendered text (plain) or given as an exact raw quote."""
        rel = str(payload.get("file") or "")
        files = self._chapter_files(ch)
        if rel not in files:
            return {}, "file does not belong to this chapter"
        raw = files[rel]
        quote = str(payload.get("quote") or "").strip()
        if not quote or len(quote) > MAX_QUOTE:
            return {}, "select a passage of text (up to 4000 characters)"
        start = raw.find(quote)
        if start < 0:  # selection from the rendered view: map plain text back to raw
            plain, idx = plain_map(raw)
            q = _norm(quote)
            pre = _norm(str(payload.get("prefix") or ""))[-40:]
            hits = [m.start() for m in re.finditer(re.escape(q), plain)]
            if not hits:
                return {}, "could not find the selected text in the source file"
            h = next((x for x in hits if plain[:x].rstrip().endswith(pre.rstrip())), hits[0]) if pre else hits[0]
            start, end = idx[h], idx[h + len(q) - 1] + 1
            quote = raw[start:end]
        end = start + len(quote)
        return {"file": rel, "quote": quote, "prefix": raw[max(0, start - MAX_CONTEXT // 2):start],
                "suffix": raw[end:end + MAX_CONTEXT // 2], "pos": start}, None

    def _add(self, ch, data, items, payload, author) -> tuple[int, dict[str, Any]]:
        kind = payload.get("kind") if payload.get("kind") in KINDS else "note"
        text = str(payload.get("text") or "").strip()
        replacement = payload.get("replacement")
        if kind == "suggest" and not isinstance(replacement, str):
            return 400, {"error": "a suggestion needs the replacement text"}
        if not text and kind != "suggest":
            return 400, {"error": "write the comment"}
        if len(text) > MAX_TEXT:
            return 400, {"error": "comment too long"}
        anchor, err = self._anchor(ch, payload)
        if err:
            return 400, {"error": err}
        c = {"id": "C-" + uuid.uuid4().hex[:8], **anchor, "author": author, "date": _now(), "kind": kind,
             "text": text, "status": "open", "replies": [], "history": [{"date": _now(), "by": author, "status": "open"}]}
        if kind == "suggest":
            c["proposal"] = {"quote": anchor["quote"], "replacement": replacement, "rationale": text, "by": author}
            self._approve(c, author)
        items.append(c)
        self._save(ch, data)
        return 200, {"ok": True, "comment": c}

    # --- called by the task validator (agent outputs) ---
    def set_proposal(self, ch: int, cid: str, proposal: dict[str, Any], task: str, agent: str) -> str | None:
        with _LOCK:
            data = self.load(ch)
            c = next((x for x in data.get("comments", []) if x.get("id") == cid), None)
            if c is None:
                return f"{cid}: comment not found"
            if c.get("status") not in ("open", "addressed"):
                return f"{cid}: status {c.get('status')} does not accept proposals"
            c["proposal"] = {"quote": proposal["quote"], "replacement": proposal["replacement"],
                             "rationale": proposal.get("rationale", ""), "by": agent, "task": task}
            c["status"] = "addressed"
            c.setdefault("history", []).append({"date": _now(), "by": agent, "status": "addressed", "task": task})
            self._save(ch, data)
        return None

    def approved_changes(self, ch: int) -> list[dict[str, Any]]:
        return [c for c in self.load(ch).get("comments", [])
                if c.get("status") == "approved" and self._proposal_sealed(c)]

    def mark_applied(self, ch: int, cid: str, task: str, agent: str, note: str = "") -> str | None:
        with _LOCK:
            data = self.load(ch)
            c = next((x for x in data.get("comments", []) if x.get("id") == cid), None)
            if c is None:
                return f"{cid}: comment not found"
            if c.get("status") != "approved" or not self._proposal_sealed(c):
                return f"{cid}: change is not approved and sealed by the author"
            src = self.cfg.workspace / c["file"]
            raw = src.read_text(encoding="utf-8", errors="ignore") if src.is_file() else ""
            if not text_shows(raw, c["proposal"].get("quote", ""), c["proposal"]["replacement"]):
                return f"{cid}: the text of {c['file']} does not show the approved change yet"
            c["status"] = "applied"
            c["proposal"]["applied_by"], c["proposal"]["applied_at"] = agent, _now()
            if note:
                c["proposal"]["applied_note"] = note[:MAX_TEXT]
            c.setdefault("history", []).append({"date": _now(), "by": agent, "status": "applied", "task": task})
            self._save(ch, data)
        return None
