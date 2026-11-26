"""Quality engine: runs the enabled check plugins over the manuscript. Read-only, no global score.

Each check returns a list of findings (`{"file","line","text","detail"}`) or a dict
`{"state": ..., "items": [...], "count": n, "note": "..."}` to override the computed state.
States: ok | warn | bad | na (not applicable / waiting for an agent review) | error (the plugin crashed).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from .citations import CitationIndex, CitationService
from .config import WorkbenchConfig
from .formats import ChapterDoc, get_adapter

RE_MASK = re.compile(r"<!--.*?-->|```.*?```", re.S)
RE_HEAD = re.compile(r"^(#{1,6})\s+(.+)$")
RE_NUM_HEAD = re.compile(r"^#{1,6}\s+(\d+)\.(\d+)\.?\s")
RE_CAPTION = re.compile(r"^\s*\*{0,2}(Table|Figure)\s+(\d+)\.(\d+)\s*[:.]")
RE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
RE_LIST = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+)")
RE_IMAGE = re.compile(r"^\s*!\[[^\]]*\]\([^)]+\)")
RE_BOLD_LINE = re.compile(r"^\*\*[^*\n]+\*\*\s*$")


def mask(raw: str) -> str:
    """Blank out comments and code fences but keep line numbers stable."""
    return RE_MASK.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), raw)


@dataclass
class Section:
    path: str
    raw: str
    chapter: int
    index: int
    lines: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.lines = mask(self.raw).splitlines()
        fence = False
        for raw_line in self.raw.splitlines():
            s = raw_line.strip()
            if s.startswith("```"):
                self.kinds.append("fence")
                fence = not fence
                continue
            if fence:
                self.kinds.append("fence")
            elif not s:
                self.kinds.append("blank")
            elif RE_HEAD.match(s):
                self.kinds.append("heading")
            elif RE_CAPTION.match(s):
                self.kinds.append("caption")
            elif s.startswith("|"):
                self.kinds.append("table")
            elif RE_IMAGE.match(s):
                self.kinds.append("image")
            elif RE_LIST.match(s):
                self.kinds.append("list")
            else:
                self.kinds.append("prose")
        self.kinds += ["blank"] * (len(self.lines) - len(self.kinds))

    @cached_property
    def num(self) -> tuple[int, int]:
        for line in self.lines:
            m = RE_NUM_HEAD.match(line.strip())
            if m:
                return int(m.group(1)), int(m.group(2))
        return self.chapter, self.index

    @cached_property
    def is_conclusion(self) -> bool:
        first = next((l for l in self.lines if RE_HEAD.match(l.strip())), "")
        return bool(re.search(r"conclu|summary|closing", first + self.path, re.I))

    def rows(self, *kinds: str):
        for i, (line, k) in enumerate(zip(self.lines, self.kinds)):
            if k in kinds:
                yield i + 1, line

    def neighbour(self, i: int, step: int) -> str:
        j = i + step
        while 0 <= j < len(self.lines):
            if self.lines[j].strip():
                return self.lines[j]
            j += step
        return ""

    def item(self, line_no: int, detail: str = "") -> dict[str, Any]:
        text = self.lines[line_no - 1].strip() if 0 < line_no <= len(self.lines) else ""
        return {"file": self.path, "line": line_no, "text": text[:260], "detail": detail}


@dataclass
class Context:
    """Everything a check may need. Expensive parts are computed lazily and shared between checks."""
    cfg: WorkbenchConfig
    chapters: list[ChapterDoc]

    @cached_property
    def sections(self) -> dict[int, list[Section]]:
        return {ch.number: [Section(s.rel_path, s.content, ch.number, i + 1) for i, s in enumerate(ch.sections)]
                for ch in self.chapters}

    @cached_property
    def citations(self) -> CitationIndex:
        return CitationIndex(CitationService(self.cfg))

    @cached_property
    def citation_uses(self) -> dict[int, list[dict[str, Any]]]:
        return {n: [u for s in secs for u in self.citations.uses_in(s.path, "\n".join(s.lines))]
                for n, secs in self.sections.items()}

    @cached_property
    def known_refs(self) -> set[tuple[str, int, int]]:
        known: set[tuple[str, int, int]] = set()
        for secs in self.sections.values():
            for sec in secs:
                known.add(("Section",) + sec.num)
                for _, line in sec.rows("heading"):
                    if m := RE_NUM_HEAD.match(line.strip()):
                        known.add(("Section", int(m.group(1)), int(m.group(2))))
                for _, line in sec.rows("caption"):
                    m = RE_CAPTION.match(line)
                    known.add((m.group(1), int(m.group(2)), int(m.group(3))))
        return known

    @cached_property
    def style_guide(self) -> list[dict[str, Any]]:
        p = self.cfg.workspace / self.cfg.style_guide_file
        if not p.is_file():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
        return data if isinstance(data, list) else data.get("entries", [])

    @cached_property
    def questions(self) -> list[dict[str, Any]]:
        from .dialogue import DialogueService
        return DialogueService(self.cfg).all_questions()

    @cached_property
    def reviews(self) -> list[dict[str, Any]]:
        from .tasks import TaskService
        return TaskService(self.cfg).valid_reviews()

    def option(self, name: str, default: Any = None) -> Any:
        return self.cfg.quality_options.get(name, default)


def _result(spec, out: Any) -> dict[str, Any]:
    base = spec.public()
    if isinstance(out, dict):
        items = list(out.get("items", []))
        state = out.get("state") or (spec.fail if items else "ok")
        return {**base, "state": state, "count": out.get("count", len(items)), "items": items[:50],
                "note": out.get("note", "")}
    items = list(out or [])
    return {**base, "state": spec.fail if items else "ok", "count": len(items), "items": items[:50], "note": ""}


def run_quality_checks(cfg: WorkbenchConfig, chapters: list[ChapterDoc] | None = None,
                       only_chapter: int | None = None) -> dict[str, Any]:
    from .plugins import load_registry
    reg = load_registry(cfg)
    if chapters is None:
        chapters = get_adapter(cfg).discover_chapters(include_content=True)
    ctx = Context(cfg, chapters)
    specs = [s for s in reg.checks.values() if s.pack in cfg.quality_packs and s.id not in cfg.disabled_checks]

    def run(spec, ch: ChapterDoc | None) -> dict[str, Any]:
        try:
            return _result(spec, spec.func(ctx, ch) if ch is not None else spec.func(ctx))
        except Exception as exc:
            return {**spec.public(), "state": "error", "count": 0, "items": [], "note": f"{type(exc).__name__}: {exc}"}

    reports = []
    for ch in chapters:
        if only_chapter is not None and ch.number != only_chapter:
            continue
        checks = [run(s, ch) for s in specs if s.scope == "chapter"]
        reports.append({"chapter": ch.number, "title": ch.title, "words": ch.words, "checks": checks,
                        "summary": {k: sum(1 for c in checks if c["state"] == k) for k in ("bad", "warn", "na", "error")}})
    return {
        "packs": cfg.quality_packs,
        "catalogue": [s.public() for s in sorted(reg.checks.values(), key=lambda s: (s.pack, s.group, s.id))],
        "plugin_errors": reg.errors,
        "style_guide_entries": len(ctx.style_guide),
        "thesis_checks": [run(s, None) for s in specs if s.scope == "thesis"],
        "chapters": reports,
    }
