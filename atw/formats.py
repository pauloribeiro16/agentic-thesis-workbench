"""Format adapters: how a thesis is laid out on disk and how its text is read.

An adapter subclasses `FormatAdapter` and is registered with `@reg.format("<id>")` from a plugin.
Built-ins: `markdown` (also `markdown-latex` and `quarto`) and `latex`. Every adapter exposes the
manuscript to the quality checks as Markdown-like text (headings with `#`), so checks are format-neutral.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import WorkbenchConfig

RE_PAREN = re.compile(r"\((?:[^()]|\([^()]*\))*\)")
_YEAR = r"(?:19|20)\d{2}[a-z]?"
RE_CITE_PART = re.compile(
    rf"{_YEAR}|[A-Z].*?,\s*(?:n\.d\.|{_YEAR})(?:,\s*{_YEAR})*(?:,\s*(?:pp?\.|cl\.|Art\.|§).*)?"
)
RE_CH_NUM = re.compile(r"(?:^|[_/\-])(?:ch(?:apter)?[_\-]?)?0*(\d{1,2})(?=[_\-.\s]|$)", re.I)


def strip_citations(text: str) -> str:
    def drop(m: re.Match) -> str:
        parts = [p.strip() for p in m.group(0)[1:-1].split(";")]
        return " " if all(RE_CITE_PART.fullmatch(p) for p in parts) else m.group(0)
    text = RE_PAREN.sub(drop, text)
    text = re.sub(r"\[@[^\]]+\]", " ", text)
    text = re.sub(r"\\(?:cite|parencite|textcite|citep|citet)\*?(?:\[[^\]]*\])*\{[^}]*\}", " ", text)
    return text


RE_SKIP_LINE = re.compile(r"^\s*(?:#{1,6}\s|\||\*{0,2}(?:Table|Figure)\s+\d+\.\d+|\*\*[^*\n]+\*\*\s*$|!\[)")


def count_words(text: str) -> int:
    """Body words: prose and lists only — no headings, tables, captions, run-in bold titles, citations or code."""
    cleaned = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    cleaned = re.sub(r"```.*?```", " ", cleaned, flags=re.S)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    body = "\n".join(l for l in cleaned.splitlines() if not RE_SKIP_LINE.match(l))
    body = re.sub(r"[*_`]", "", strip_citations(body))
    return len(re.findall(r"[0-9A-Za-zÀ-ÿ][0-9A-Za-zÀ-ÿ'’\-]*", body))


@dataclass
class SectionDoc:
    filename: str
    rel_path: str
    words: int
    content: str = ""   # normalised (Markdown-like) text used by checks and the manuscript view

    def to_dict(self, include_content: bool) -> dict[str, Any]:
        d: dict[str, Any] = {"filename": self.filename, "path": self.rel_path, "words": self.words}
        if include_content:
            d["content"] = self.content
        return d


@dataclass
class ChapterDoc:
    number: int
    title: str
    directory: str
    words: int
    target_min: int | None
    target_max: int | None
    sections: list[SectionDoc] = field(default_factory=list)
    format_adapter: str = "markdown"

    def to_dict(self, include_content: bool = False) -> dict[str, Any]:
        return {
            "number": self.number, "title": self.title, "directory": self.directory, "words": self.words,
            "target": [self.target_min, self.target_max] if self.target_max else None,
            "section_count": len(self.sections),
            "format": self.format_adapter,
            "sections": [s.to_dict(include_content) for s in self.sections],
        }


def _extract_title(path: Path, is_dir: bool = False) -> str:
    name = path.name if is_dir else path.stem
    cleaned = re.sub(r"^\d+[_\-\s.]*(?:CHAPTER[_\-\s]*\d*[_\-\s]*)?", "", name, flags=re.I)
    return cleaned.replace("_", " ").replace("-", " ").strip() or name


def _chapter_num(rel: Path, fallback: int) -> int:
    for part in rel.parts:
        m = RE_CH_NUM.search(part)
        if m and 1 <= int(m.group(1)) <= 30:
            return int(m.group(1))
    return fallback


class FormatAdapter:
    """Base adapter for file-per-section layouts. Override `normalise` for non-Markdown sources."""

    id = "markdown"

    def __init__(self, cfg: WorkbenchConfig) -> None:
        self.cfg = cfg

    def normalise(self, raw: str) -> str:
        return raw

    def files(self) -> list[Path]:
        ws = self.cfg.workspace
        excl = set(self.cfg.exclude_dirs)
        return sorted(
            p for p in ws.glob(self.cfg.chapters_glob)
            if p.is_file()
            and not (set(p.relative_to(ws).parts[:-1]) & excl)
            and p.name not in self.cfg.exclude_files
        )

    def discover_chapters(self, include_content: bool = False) -> list[ChapterDoc]:
        ws = self.cfg.workspace
        grouped: dict[int, list[Path]] = {}
        for idx, p in enumerate(self.files(), start=1):
            grouped.setdefault(_chapter_num(p.relative_to(ws), idx), []).append(p)
        chapters: list[ChapterDoc] = []
        for num in sorted(grouped):
            files = sorted(grouped[num], key=lambda x: x.name)
            parent = files[0].parent
            title = _extract_title(parent, True) if parent != ws and len(files) > 1 else _extract_title(files[0])
            sections, total = [], 0
            for f in files:
                text = self.normalise(f.read_text(encoding="utf-8", errors="ignore"))
                wc = count_words(text)
                total += wc
                sections.append(SectionDoc(f.name, str(f.relative_to(ws)), wc, text if include_content else ""))
            tmin, tmax = self.cfg.word_target(num) or (None, None)
            chapters.append(ChapterDoc(num, title, str(files[0].relative_to(ws).parent), total, tmin, tmax,
                                       sections, self.id))
        return chapters

    def sources_for(self, chapter: int) -> list[Path]:
        ws = self.cfg.workspace
        return [p for i, p in enumerate(self.files(), 1) if _chapter_num(p.relative_to(ws), i) == chapter]


class LatexAdapter(FormatAdapter):
    """Reads `.tex` chapters and exposes them as Markdown-like text for the checks."""

    id = "latex"
    HEADS = (("chapter", "#"), ("section", "##"), ("subsection", "###"), ("subsubsection", "####"))

    def normalise(self, raw: str) -> str:
        text = re.sub(r"(?<!\\)%.*$", "", raw, flags=re.M)
        for cmd, hashes in self.HEADS:
            text = re.sub(rf"\\{cmd}\*?(?:\[[^\]]*\])?\{{([^}}]*)\}}", rf"{hashes} \1", text)
        text = re.sub(r"\\caption\{([^}]*)\}", r"\1", text)
        text = re.sub(r"\\(?:emph|textit)\{([^}]*)\}", r"*\1*", text)
        text = re.sub(r"\\textbf\{([^}]*)\}", r"**\1**", text)
        text = re.sub(r"\\(?:label|ref|input|include|begin|end)\{[^}]*\}", " ", text)
        return text


def get_adapter(cfg: WorkbenchConfig) -> FormatAdapter:
    from .plugins import load_registry
    cls = load_registry(cfg).formats.get(cfg.format_adapter) or FormatAdapter
    return cls(cfg)
