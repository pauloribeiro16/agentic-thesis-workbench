"""Model-agnostic multi-agent dialogue: parsing, governance (who may change a state) and sealed decisions.

Governance rule: agents only *propose* states. `APPROVED` (or any author-only state) takes effect only
from a moderator decision block carrying a valid HMAC seal (when `sign_decisions = true`). Anything else
that claims approval is shown as an unauthorised claim and never changes the question state.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import WorkbenchConfig

QID = r"(?:QT-\d+|Q\d+)"
RE_QBLOCK = re.compile(rf"^\*\*({QID})\b\s*[—–-]?\s*(.*?)\*\*\s*$")
RE_ROW = re.compile(rf"^\|\s*\**`?({QID})`?\**\s*\|")
RE_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
NEED_STATES = {"AGENT_CONSENSUS", "AGENT_DEADLOCK", "AUTHOR_RESERVED", "SINGLE_PROPOSAL"}
AUTHOR_ONLY_STATES = {"APPROVED"}


@dataclass(frozen=True)
class Profile:
    """Vocabulary of a dialogue format. `en` is canonical; `pt-legacy` reads/writes older Portuguese threads."""
    name: str
    turn_words: tuple[str, ...]
    verdicts: tuple[str, ...]
    moderator_heading: re.Pattern
    decision: re.Pattern
    seal_tag: str
    state_aliases: tuple[tuple[str, str], ...]
    skip_files: tuple[str, ...]
    skip_substrings: tuple[str, ...] = ()

    def seal_re(self) -> re.Pattern:
        return re.compile(r"^<!--\s*(?:moderator|moderador):\s*v1\s+([0-9a-f]{64})\s*-->\s*$")


_EN_STATES = (
    ("AUTHOR_RESERVED", "AUTHOR_RESERVED"), ("AGENT_CONSENSUS", "AGENT_CONSENSUS"),
    ("AGENT_DEADLOCK", "AGENT_DEADLOCK"), ("SINGLE_PROPOSAL", "SINGLE_PROPOSAL"),
    ("APPROVED", "APPROVED"), ("CLOSED", "APPROVED"), ("REJECTED", "REJECTED"),
    ("DEADLOCK", "AGENT_DEADLOCK"), ("RESERVED", "AUTHOR_RESERVED"), ("CONSENSUS", "AGENT_CONSENSUS"),
    ("OPEN", "OPEN"),
)
_PT_STATES = (
    ("CONSENSO_AGENTES", "AGENT_CONSENSUS"), ("RESERVADA_AUTOR", "AUTHOR_RESERVED"), ("IMPASSE_AGENTES", "AGENT_DEADLOCK"),
    ("AUTOR", "AUTHOR_RESERVED"), ("RESERVADA", "AUTHOR_RESERVED"), ("CONSENSO", "AGENT_CONSENSUS"), ("IMPASSE", "AGENT_DEADLOCK"),
    ("PROPOSTA_UNICA", "SINGLE_PROPOSAL"), ("PROPOSTA ÚNICA", "SINGLE_PROPOSAL"), ("APROVADA", "APPROVED"),
    ("FECHADA", "APPROVED"), ("REJEITADA", "REJECTED"), ("ABERTA", "OPEN"),
)

PROFILES: dict[str, Profile] = {
    "en": Profile(
        name="en",
        turn_words=("Turn",),
        verdicts=("AGREE WITH CHANGES", "PARTIALLY AGREE", "AGREE", "DISAGREE"),
        moderator_heading=re.compile(r"^Moderator Decision\b", re.I),
        decision=re.compile(rf"Decision on\s+`?({QID})`?\s*\(`([^`]+)`\)", re.I),
        seal_tag="moderator",
        state_aliases=_EN_STATES,
        skip_files=("README.md", "IMPLEMENTATION_LOG.md"),
    ),
    "pt-legacy": Profile(
        name="pt-legacy",
        turn_words=("Turn", "Vez"),
        verdicts=("AGREE WITH CHANGES", "PARTIALLY AGREE", "AGREE", "DISAGREE",
                  "CONCORDO EM PARTE", "CONCORDO", "DISCORDO"),
        moderator_heading=re.compile(r"^(?:Moderator Decision|Delibera[çc][ãa]o do Moderador)\b", re.I),
        decision=re.compile(rf"(?:Decision on|Decis[ãa]o sobre)\s+`?({QID})`?\s*\(`([^`]+)`\)", re.I),
        seal_tag="moderador",
        state_aliases=_PT_STATES + _EN_STATES,
        skip_files=("README.md", "IMPLEMENTATION_LOG.md"),
        skip_substrings=("_anexo",),
    ),
}


def profile_for(cfg: WorkbenchConfig) -> Profile:
    return PROFILES.get(cfg.dialogue_profile, PROFILES["en"])


def canonical_state(raw: str, profile: Profile | None = None) -> str:
    norm = raw.replace("`", "").replace("*", "").strip().upper().replace("-", "_")
    for token, canon in (profile or PROFILES["pt-legacy"]).state_aliases:
        if re.search(rf"(?<![A-Z_]){re.escape(token)}(?![A-Z_])", norm):
            return canon
    return "OPEN"


def agent_color_slot(name: str, is_moderator: bool = False) -> str:
    if is_moderator:
        return "mod"
    if not name:
        return "0"
    return str(hashlib.sha256(name.strip().lower().encode("utf-8")).digest()[0] % 4)


def parse_heading(heading: str, cfg: WorkbenchConfig, profile: Profile) -> tuple[str, str]:
    """Returns (speaker, kind). kind is 'moderator' only for the moderator decision heading or when the
    speaker part is exactly the configured moderator name — never by substring."""
    if profile.moderator_heading.search(heading):
        return cfg.moderator_name, "moderator"
    parts = [p.strip() for p in re.split(r"\s+[—–]\s+|\s+-\s+", heading) if p.strip()]
    words = "|".join(re.escape(w) for w in profile.turn_words)
    speaker = ""
    for p in parts:
        if RE_DATE.fullmatch(p) or re.fullmatch(rf"(?:{words})\s+\d+", p, re.I):
            continue
        speaker = p
        break
    if not speaker:
        return "", "section"
    base = re.sub(r"\s*\(.*?\)\s*$", "", speaker).strip()
    if cfg.moderator_name and base.lower() == cfg.moderator_name.lower():
        return cfg.moderator_name, "moderator"
    if not re.match(rf"^(?:{words})\b", heading, re.I) and not RE_DATE.search(heading):
        return speaker, "section"  # a plain "## Background" heading, not a turn
    return speaker, "agent"


class ModeratorSeal:
    """HMAC-SHA256 seal for human moderator decisions. The key never leaves the author's machine."""

    def __init__(self, cfg: WorkbenchConfig) -> None:
        self.enabled = cfg.sign_decisions
        self.profile = profile_for(cfg)
        self.key_path = (
            Path(cfg.key_path).expanduser() if cfg.key_path
            else Path.home() / ".config" / "agentic-thesis-workbench" / "moderator.key"
        )

    def _key(self, create: bool = False) -> bytes | None:
        if self.key_path.exists():
            return self.key_path.read_bytes().strip()
        if not create:
            return None
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(secrets.token_hex(32).encode("ascii"))
        return self.key_path.read_bytes().strip()

    def canonical_body(self, lines: list[str]) -> str:
        rx = self.profile.seal_re()
        out = [l.rstrip() for l in lines if not rx.match(l.strip())]
        while out and out[-1] in ("", "---"):
            out.pop()
        while out and out[0] in ("", "---"):
            out.pop(0)
        return "\n".join(out)

    def mac(self, file_name: str, lines: list[str], key: bytes) -> str:
        msg = f"{file_name}\n{self.canonical_body(lines)}".encode("utf-8")
        return hmac.new(key, msg, hashlib.sha256).hexdigest()

    def sign(self, file_name: str, block: str) -> str:
        body = block.rstrip("\n")
        if not self.enabled:
            return body + "\n"
        k = self._key(create=True)
        return f"{body}\n\n<!-- {self.profile.seal_tag}: v1 {self.mac(file_name, body.splitlines(), k)} -->\n"

    def sign_payload(self, payload: str) -> str:
        """Seal an arbitrary approval (e.g. an approved text change). Empty when signing is disabled."""
        if not self.enabled:
            return ""
        return hmac.new(self._key(create=True), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_payload(self, payload: str, seal: str) -> bool:
        if not self.enabled:
            return True
        k = self._key(create=False)
        return bool(k and seal) and hmac.compare_digest(seal, hmac.new(k, payload.encode("utf-8"), hashlib.sha256).hexdigest())

    def verify(self, file_name: str, lines: list[str]) -> bool:
        rx = self.profile.seal_re()
        seal = next((rx.match(l.strip()).group(1) for l in lines if rx.match(l.strip())), None)
        k = self._key(create=False)
        if not k or not seal:
            return False
        return hmac.compare_digest(seal, self.mac(file_name, lines, k))


def _new_q(qid: str, title: str, thread: str) -> dict[str, Any]:
    return {"id": qid, "title": title or qid, "state": "OPEN", "thread": thread, "owner": "", "summary": "",
            "verdicts": [], "history": [], "authenticated": False, "unauthorized_claims": []}


class DialogueService:
    """Reads append-only dialogue threads and appends sealed moderator decisions."""

    def __init__(self, cfg: WorkbenchConfig) -> None:
        self.cfg = cfg
        self.profile = profile_for(cfg)
        self.seal = ModeratorSeal(cfg)

    @property
    def root(self) -> Path:
        return self.cfg.workspace / self.cfg.dialogue_dir

    def thread_paths(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return [p for p in sorted(self.root.glob("*.md"))
                if p.name not in self.profile.skip_files
                and not any(s in p.name for s in self.profile.skip_substrings)]

    def list_threads(self) -> list[dict[str, Any]]:
        return [self.parse_thread(p) for p in self.thread_paths()]

    def all_questions(self) -> list[dict[str, Any]]:
        return [q for t in self.list_threads() for q in t["questions"]]

    def parse_thread(self, path: Path) -> dict[str, Any]:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        lines = raw.splitlines()
        turns: list[dict[str, Any]] = []
        cur: dict[str, Any] | None = None
        for i, line in enumerate(lines):
            if line.startswith("## ") and not line.startswith("###"):
                if cur is not None:
                    turns.append(cur)
                heading = line[3:].strip()
                speaker, kind = parse_heading(heading, self.cfg, self.profile)
                dm = RE_DATE.search(heading)
                cur = {"heading": heading, "agent": speaker, "kind": kind,
                       "slot": agent_color_slot(speaker, kind == "moderator"),
                       "date": dm.group(1) if dm else "", "line": i + 1, "lines": [line]}
            elif cur is not None:
                cur["lines"].append(line)
        if cur is not None:
            turns.append(cur)

        questions: dict[str, dict[str, Any]] = {}
        agents_seen: set[str] = set()
        verdict_rx = re.compile(r"`?\b(" + "|".join(re.escape(v) for v in self.profile.verdicts) + r")\b`?", re.I)
        seal_rx = self.profile.seal_re()

        for idx, t in enumerate(turns):
            body = t["lines"][1:]
            t["idx"] = idx
            t["sealed"] = self.seal.verify(path.name, t["lines"]) if t["kind"] == "moderator" else False
            t["md"] = "\n".join(l for l in body if not seal_rx.match(l.strip())).strip()
            del t["lines"]
            if t["kind"] == "agent":
                agents_seen.add(t["agent"])
            authority = t["kind"] == "moderator" and (t["sealed"] or not self.cfg.sign_decisions)
            open_q: str | None = None

            for bl in body:
                s = bl.strip()
                qm = RE_QBLOCK.match(s)
                if qm:
                    qid, title = qm.group(1), qm.group(2).strip()
                    q = questions.setdefault(qid, _new_q(qid, title, path.name))
                    if title and q["title"] == qid:
                        q["title"] = title
                    open_q = qid
                    continue
                if open_q and t["kind"] == "agent":
                    vm = verdict_rx.search(s)
                    if vm and ("verdict" in s.lower() or "veredicto" in s.lower() or s.startswith("-")):
                        questions[open_q]["verdicts"].append(
                            {"agent": t["agent"], "verdict": vm.group(1).upper(), "turn": idx})
                        open_q = None
                rm = RE_ROW.match(s)
                if rm and t["kind"] in ("agent", "moderator"):
                    cells = [c.strip().strip("*`").strip() for c in s.strip("|").split("|")]
                    if len(cells) >= 3:
                        qid = rm.group(1)
                        q = questions.setdefault(qid, _new_q(qid, cells[1], path.name))
                        if cells[1]:
                            q["title"] = cells[1]
                        if len(cells) > 3:
                            q["owner"] = cells[3]
                        if len(cells) > 4:
                            q["summary"] = cells[4]
                        st = canonical_state(cells[2], self.profile)
                        self._apply(q, st, t, idx, authority, source="table")
                dm2 = self.profile.decision.search(bl)
                if dm2 and t["kind"] == "moderator":
                    qid = dm2.group(1)
                    q = questions.setdefault(qid, _new_q(qid, qid, path.name))
                    st = canonical_state(dm2.group(2), self.profile)
                    self._apply(q, st, t, idx, authority, source="decision", note=bl.strip())

        qs = list(questions.values())
        for q in qs:
            q["needs_author"] = q["state"] in NEED_STATES
        return {
            "file": path.name,
            "sha": hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],
            "turns_count": len(turns),
            "agents": sorted(agents_seen),
            "questions": qs,
            "turns": turns,
        }

    @staticmethod
    def _apply(q: dict[str, Any], st: str, t: dict[str, Any], idx: int, authority: bool, source: str,
               note: str = "") -> None:
        author_only = st in AUTHOR_ONLY_STATES
        if t["kind"] == "agent" and author_only and q["authenticated"] and q["state"] == st:
            return  # an agent restating a state the author already sealed is not a claim
        if t["kind"] == "agent" and author_only:
            q["unauthorized_claims"].append({"turn": idx, "agent": t["agent"], "state": st, "source": source})
            return
        if t["kind"] == "moderator" and not authority:
            q["unauthorized_claims"].append({"turn": idx, "agent": t["agent"], "state": st, "source": "unsealed"})
            return
        if t["kind"] == "agent" and q["authenticated"] and q["state"] in AUTHOR_ONLY_STATES:
            # agents cannot reopen or move an approved question; they must raise a new one
            q["unauthorized_claims"].append({"turn": idx, "agent": t["agent"], "state": st, "source": source})
            return
        if not q["history"] or q["history"][-1]["state"] != st:
            q["history"].append({"turn": idx, "agent": t["agent"], "state": st, "date": t["date"]})
        q["state"] = st
        if t["kind"] == "moderator":
            q["authenticated"] = bool(t["sealed"])
            if note:
                q["decision_note"] = note

    def append_decision(self, thread_file: str, expected_sha: str, decisions: list[dict[str, str]]) -> tuple[bool, str]:
        target = (self.root / thread_file).resolve()
        if self.root.resolve() not in target.parents or not target.is_file() or target.suffix != ".md":
            return False, "Thread file not found"
        raw = target.read_text(encoding="utf-8")
        if expected_sha and hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16] != expected_sha:
            return False, "Conflict: thread modified concurrently"
        valid = [d for d in decisions if re.fullmatch(QID, str(d.get("id", "")))]
        if not valid:
            return False, "No valid question ids"
        today = dt.date.today().isoformat()
        qids = ", ".join(f"`{d['id']}`" for d in valid)
        name = self.cfg.moderator_name
        pt = self.profile.name == "pt-legacy"
        head = (f"## Deliberação do Moderador ({name}) — {today} (sobre {qids})" if pt
                else f"## Moderator Decision ({name}) — {today} (on {qids})")
        out = [head, ""]
        for d in valid:
            st = canonical_state(str(d.get("state", "APPROVED")), self.profile)
            note = " ".join(str(d.get("note") or "").split())[:2000]
            if pt:
                label = {"APPROVED": f"APROVADA ({name})", "REJECTED": "REJEITADA", "OPEN": "ABERTA",
                         "AUTHOR_RESERVED": "RESERVADA"}.get(st, st)
                out.append(f"- **Decisão sobre `{d['id']}` (`{label}`):** {note or 'Aprovada na bancada.'}")
            else:
                out.append(f"- **Decision on `{d['id']}` (`{st}`):** {note or 'Decided in the workbench.'}")
        block = self.seal.sign(target.name, "\n".join(out))
        target.write_text(raw.rstrip("\n") + "\n\n" + block, encoding="utf-8")
        return True, "ok"

    def append_message(self, thread_file: str, lines: list[str]) -> tuple[bool, str]:
        """Append a sealed moderator block that records information without changing any question state."""
        target = (self.root / thread_file).resolve()
        if self.root.resolve() not in target.parents or not target.is_file() or target.suffix != ".md":
            return False, "Thread file not found"
        raw = target.read_text(encoding="utf-8")
        today = dt.date.today().isoformat()
        name = self.cfg.moderator_name
        if self.profile.name == "pt-legacy":
            out = [f"## Deliberação do Moderador ({name}) — {today} (mensagem aos agentes)", "",
                   "**Mensagem do moderador aos agentes:**", ""]
        else:
            out = [f"## Moderator Decision ({name}) — {today} (message to agents)", "", "**Message to the agents:**", ""]
        block = self.seal.sign(target.name, "\n".join(out + [str(l) for l in lines]))
        target.write_text(raw.rstrip("\n") + "\n\n" + block, encoding="utf-8")
        return True, "ok"
