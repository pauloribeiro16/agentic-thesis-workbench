"""Pluggable thesis format adapters (Markdown+LaTeX, pure LaTeX, Markdown/Quarto)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import WorkbenchConfig

RE_PAREN = re.compile(r"\((?:[^()]|\([^()]*\))*\)")
_YEAR = r"(?:19|20)\d{2}[a-z]?"
RE_CITE_PART = re.compile(
    rf"{_YEAR}"
    rf"|[A-Z].*?,\s*(?:n\.d\.|{_YEAR})(?:,\s*{_YEAR})*(?:,\s*(?:pp?\.|cl\.|Art\.|§).*)?"
)
RE_CH_NUM = re.compile(r"(?:^|[_/\-])(?:ch(?:apter)?[_\-]?)?0*(\d{1,2})\b", re.I)
RE_LATEX_CMD = re.compile(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})?")


def strip_citations(text: str) -> str:
    def drop(m: re.Match) -> str:
        parts = [p.strip() for p in m.group(0)[1:-1].split(";")]
        return " " if all(RE_CITE_PART.fullmatch(p) for p in parts) else m.group(0)

    text = RE_PAREN.sub(drop, text)
    text = re.sub(r"\[@[^\]]+\]", " ", text)
    return text


def count_words(text: str, is_latex: bool = False) -> int:
    cleaned = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    cleaned = re.sub(r"```.*?```", " ", cleaned, flags=re.S)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    if is_latex:
        cleaned = re.sub(r"(?m)%.*$", " ", cleaned)
        cleaned = RE_LATEX_CMD.sub(" ", cleaned)
    cleaned = strip_citations(cleaned)
    return len(re.findall(r"[0-9A-Za-zÀ-ÿ][0-9A-Za-zÀ-ÿ'’\-]*", cleaned))


@dataclass
class SectionDoc:
    filename: str
    rel_path: str
    words: int
    content: str = ""


@dataclass
class ChapterDoc:
    number: int
    title: str
    directory: str
    words: int
    target_min: int
    target_max: int
    sections: list[SectionDoc] = field(default_factory=list)
    format_adapter: str = "markdown-latex"

    def to_dict(self, include_content: bool = False) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "directory": self.directory,
            "words": self.words,
            "target": [self.target_min, self.target_max],
            "section_count": len(self.sections),
            "format": self.format_adapter,
            "sections": [
                {
                    "filename": s.filename,
                    "path": s.rel_path,
                    "words": s.words,
                    **({"content": s.content} if include_content else {}),
                }
                for s in self.sections
            ],
        }


def _extract_title(path: Path, is_dir: bool = False) -> str:
    name = path.name if is_dir else path.stem
    cleaned = re.sub(r"^\d+[_\-\s]*(?:CHAPTER[_\-\s]*\d*[_\-\s]*)?", "", name, flags=re.I)
    return cleaned.replace("_", " ").replace("-", " ").strip() or name


def _extract_chapter_num(rel: Path, fallback: int) -> int:
    for part in rel.parts:
        m = RE_CH_NUM.search(part)
        if m:
            num = int(m.group(1))
            if 1 <= num <= 30:
                return num
    return fallback


class FormatAdapter:
    """Discovers and reads chapters according to the workspace thesis.toml."""

    def __init__(self, cfg: WorkbenchConfig) -> None:
        self.cfg = cfg

    @property
    def is_latex(self) -> bool:
        return self.cfg.format_adapter == "latex"

    def discover_chapters(self, include_content: bool = False) -> list[ChapterDoc]:
        ws = self.cfg.workspace
        matched = sorted(
            p for p in ws.glob(self.cfg.chapters_glob)
            if p.is_file()
            and ".git" not in p.parts
            and ".thesis" not in p.parts
            and "AGENT_DIALOGUE" not in p.parts
            and "LITERATURE" not in p.parts
            and "Archive" not in p.parts
            and not p.name.startswith("00_")
            and p.name.lower() != "readme.md"
        )

        grouped: dict[int, list[Path]] = {}
        for idx, p in enumerate(matched, start=1):
            rel = p.relative_to(ws)
            num = _extract_chapter_num(rel, fallback=idx)
            grouped.setdefault(num, []).append(p)

        chapters: list[ChapterDoc] = []
        for num in sorted(grouped):
            files = sorted(grouped[num], key=lambda x: x.name)
            first_rel = files[0].relative_to(ws)
            parent = files[0].parent
            title = (
                _extract_title(parent, is_dir=True)
                if parent != ws and len(files) > 1
                else _extract_title(files[0], is_dir=False)
            )
            sections: list[SectionDoc] = []
            total_words = 0
            for f in files:
                text = f.read_text(encoding="utf-8", errors="ignore")
                wc = count_words(text, is_latex=self.is_latex)
                total_words += wc
                sections.append(
                    SectionDoc(
                        filename=f.name,
                        rel_path=str(f.relative_to(ws)),
                        words=wc,
                        content=text if include_content else "",
                    )
                )
            tmin, tmax = self.cfg.word_targets.get(num, self.cfg.default_word_target)
            chapters.append(
                ChapterDoc(
                    number=num,
                    title=title,
                    directory=str(first_rel.parent),
                    words=total_words,
                    target_min=tmin,
                    target_max=tmax,
                    sections=sections,
                    format_adapter=self.cfg.format_adapter,
                )
            )
        return chapters
