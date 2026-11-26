"""Model-agnostic multi-agent dialogue parser, HMAC moderator sealing, comments & proposals."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

from .config import WorkbenchConfig

QID = r"(?:QT-\d+|Q\d+)"
RE_TURN = re.compile(r"^##\s+(?:Turn|Vez|\d+\.)?\s*(.+?)\s*$", re.I)
RE_QBLOCK = re.compile(rf"^\*\*({QID})\b\s*[—–-]?\s*(.*?)\*\*\s*$")
RE_VERDICT = re.compile(
    r"`?\b(AGREE WITH CHANGES|PARTIALLY AGREE|AGREE|DISAGREE|CONCORDO EM PARTE|CONCORDO|DISCORDO)\b`?",
    re.I,
)
RE_ROW = re.compile(rf"^\|\s*\**`?({QID})`?\**\s*\|")
RE_MOD_DECISION = re.compile(rf"(?:Decision on|Decis[ãa]o sobre)\s+`?({QID})`?\s*\(`([^`]+)`\)", re.I)
RE_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
RE_SEAL = re.compile(r"^<!--\s*(?:moderator|moderador):\s*v1\s+([0-9a-f]{64})\s*-->\s*$")
NOT_THREADS = {"README.md", "IMPLEMENTATION_LOG.md"}

STATE_ALIASES = [
    ("APPROVED", "APPROVED"),
    ("APROVADA", "APPROVED"),
    ("CLOSED", "APPROVED"),
    ("FECHADA", "APPROVED"),
    ("DEADLOCK", "AGENT_DEADLOCK"),
    ("IMPASSE", "AGENT_DEADLOCK"),
    ("DISAGREE", "AGENT_DEADLOCK"),
    ("RESERVED", "AUTHOR_RESERVED"),
    ("RESERVADA", "AUTHOR_RESERVED"),
    ("AUTHOR", "AUTHOR_RESERVED"),
    ("AUTOR", "AUTHOR_RESERVED"),
    ("CONSENSUS", "AGENT_CONSENSUS"),
    ("CONSENSO", "AGENT_CONSENSUS"),
    ("SINGLE_PROPOSAL", "SINGLE_PROPOSAL"),
    ("PROPOSTA_UNICA", "SINGLE_PROPOSAL"),
    ("OPEN", "OPEN"),
    ("ABERTA", "OPEN"),
]


def canonical_state(raw: str) -> str:
    norm = raw.replace("`", "").replace("*", "").strip().upper()
    for token, canon in STATE_ALIASES:
        if token in norm:
            return canon
    return "OPEN"


def agent_color_slot(name: str, is_moderator: bool = False) -> str:
    if is_moderator:
        return "mod"
    if not name:
        return "0"
    digest = hashlib.sha256(name.strip().lower().encode("utf-8")).digest()
    return str(digest[0] % 4)


def parse_agent_from_heading(heading: str, moderator_name: str) -> tuple[str, str]:
    """Model-agnostic parser: extracts speaker identity from any 'Turn N — <Agent> — YYYY-MM-DD' heading."""
    h_low = heading.lower()
    mod_low = moderator_name.lower()
    if "moderator" in h_low or "moderador" in h_low or (mod_low and mod_low in h_low):
        return moderator_name, "moderator"
    parts = [p.strip() for p in re.split(r"\s+[—–-]\s+", heading) if p.strip()]
    filtered = [
        p for p in parts
        if not RE_DATE.fullmatch(p) and not re.match(r"^(?:turn|vez)\s+\d+$", p, re.I)
    ]
    if filtered:
        return filtered[0], "agent"
    return "Agent", "agent"


class ModeratorSeal:
    """Optional HMAC-SHA256 authentication for human moderator decisions."""

    def __init__(self, cfg: WorkbenchConfig) -> None:
        self.enabled = cfg.sign_decisions
        self.key_path = (
            Path(cfg.key_path).expanduser()
            if cfg.key_path
            else Path.home() / ".config" / "agentic-thesis-workbench" / "moderator.key"
        )

    def _key(self, create: bool = False) -> bytes | None:
        if not self.enabled:
            return None
        if self.key_path.exists():
            return self.key_path.read_bytes().strip()
        if not create:
            return None
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(secrets.token_hex(32).encode("ascii"))
        return self.key_path.read_bytes().strip()

    @staticmethod
    def canonical_body(lines: list[str]) -> str:
        out = [l.rstrip() for l in lines if not RE_SEAL.match(l.strip())]
        while out and out[-1] in ("", "---"):
            out.pop()
        while out and out[0] in ("", "---"):
            out.pop(0)
        return "\n".join(out)

    def sign(self, file_name: str, block: str) -> str:
        k = self._key(create=True)
        body = block.rstrip("\n")
        if not k:
            return body + "\n"
        sig = hmac.new(k, f"{file_name}\n{self.canonical_body(body.splitlines())}".encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{body}\n\n<!-- moderator: v1 {sig} -->\n"

    def verify(self, file_name: str, lines: list[str], seal: str | None) -> bool:
        k = self._key(create=False)
        if not k or not seal:
            return False
        expected = hmac.new(k, f"{file_name}\n{self.canonical_body(lines)}".encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(seal, expected)


class DialogueService:
    """Reads append-only dialogue threads, proposals, and anchored comments."""

    def __init__(self, cfg: WorkbenchConfig) -> None:
        self.cfg = cfg
        self.seal = ModeratorSeal(cfg)

    @property
    def dialogue_root(self) -> Path:
        return self.cfg.workspace / self.cfg.dialogue_dir

    def list_threads(self) -> list[dict[str, Any]]:
        root = self.dialogue_root
        if not root.is_dir():
            return []
        threads: list[dict[str, Any]] = []
        for p in sorted(root.glob("*.md")):
            if p.name in NOT_THREADS:
                continue
            threads.append(self.parse_thread(p))
        return threads

    def parse_thread(self, path: Path) -> dict[str, Any]:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        lines = raw.splitlines()
        turns: list[dict[str, Any]] = []
        cur: dict[str, Any] | None = None

        for i, line in enumerate(lines):
            if line.startswith("## ") and not line.startswith("###"):
                if cur is not None:
                    turns.append(cur)
                heading = line[3:].strip()
                speaker, kind = parse_agent_from_heading(heading, self.cfg.moderator_name)
                dm = RE_DATE.search(heading)
                cur = {
                    "heading": heading,
                    "agent": speaker,
                    "kind": kind,
                    "slot": agent_color_slot(speaker, is_moderator=(kind == "moderator")),
                    "date": dm.group(1) if dm else "",
                    "line": i + 1,
                    "lines": [line],
                }
            elif cur is not None:
                cur["lines"].append(line)
        if cur is not None:
            turns.append(cur)

        questions: dict[str, dict[str, Any]] = {}
        agents_seen: set[str] = set()

        for idx, t in enumerate(turns):
            body_lines = t["lines"][1:]
            t["idx"] = idx
            t["md"] = "\n".join(body_lines).strip()
            seal_hex = next(
                (RE_SEAL.match(l.strip()).group(1) for l in body_lines if RE_SEAL.match(l.strip())),
                None,
            )
            t["sealed"] = self.seal.verify(path.name, t["lines"], seal_hex) if t["kind"] == "moderator" else False
            del t["lines"]

            if t["kind"] == "agent":
                agents_seen.add(t["agent"])

            for bl in body_lines:
                qm = RE_QBLOCK.match(bl.strip())
                if qm:
                    qid, title = qm.group(1), qm.group(2).strip()
                    q = questions.setdefault(
                        qid,
                        {"id": qid, "title": title or qid, "state": "OPEN", "thread": path.name, "verdicts": []},
                    )
                    if title and q["title"] == qid:
                        q["title"] = title
                rm = RE_ROW.match(bl.strip())
                if rm:
                    cells = [c.strip().strip("*`") for c in bl.strip().strip("|").split("|")]
                    if len(cells) >= 3:
                        qid = rm.group(1)
                        q = questions.setdefault(
                            qid,
                            {"id": qid, "title": cells[1] or qid, "state": "OPEN", "thread": path.name, "verdicts": []},
                        )
                        if cells[1]:
                            q["title"] = cells[1]
                        q["state"] = canonical_state(cells[2])
                dm2 = RE_MOD_DECISION.search(bl)
                if dm2:
                    qid, st = dm2.group(1), canonical_state(dm2.group(2))
                    q = questions.setdefault(
                        qid,
                        {"id": qid, "title": qid, "state": st, "thread": path.name, "verdicts": []},
                    )
                    q["state"] = st
                    q["authenticated"] = t["sealed"]

        return {
            "file": path.name,
            "sha": sha,
            "turns_count": len(turns),
            "agents": sorted(agents_seen),
            "questions": list(questions.values()),
            "turns": turns,
        }

    def append_decision(self, thread_file: str, expected_sha: str, decisions: list[dict[str, str]]) -> tuple[bool, str]:
        target = (self.dialogue_root / thread_file).resolve()
        if self.dialogue_root.resolve() not in target.parents or not target.is_file():
            return False, "Thread file not found"
        raw = target.read_text(encoding="utf-8")
        cur_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        if expected_sha and cur_sha != expected_sha:
            return False, "Conflict: thread modified concurrently"

        today = dt.date.today().isoformat()
        qids = ", ".join(f"`{d['id']}`" for d in decisions)
        lines = [f"## Moderator Decision ({self.cfg.moderator_name}) — {today} (on {qids})", ""]
        for d in decisions:
            st = canonical_state(d.get("state", "APPROVED"))
            note = (d.get("note") or "Approved via workbench.").strip()
            lines.append(f"- **Decision on `{d['id']}` (`{st}`):** {note}")

        block = self.seal.sign(target.name, "\n".join(lines))
        sep = "\n\n" if raw.endswith("\n") else "\n\n"
        target.write_text(raw.rstrip("\n") + sep + block, encoding="utf-8")
        return True, "ok"

    def load_proposals(self) -> list[dict[str, Any]]:
        p = self.cfg.workspace / self.cfg.proposals_file
        if not p.is_file():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else data.get("proposals", [])
        except Exception:
            return []

    def load_comments(self) -> dict[str, list[dict[str, Any]]]:
        d = self.cfg.workspace / self.cfg.comments_dir
        if not d.is_dir():
            return {}
        out: dict[str, list[dict[str, Any]]] = {}
        for p in sorted(d.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                out[p.stem] = data if isinstance(data, list) else data.get("comments", [])
            except Exception:
                continue
        return out
