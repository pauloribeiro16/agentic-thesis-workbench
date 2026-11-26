"""Page budget: pages are the limit, words are only a reference.

From the last compilation we know the chapter's pages (up to a LaTeX label, so the reference list does not
count). In-text citations do take space in the PDF, so the pages *without citations* are estimated from the
share of the body text that citations occupy. Dividing the words at compile time by those pages gives this
chapter's own words-per-page (tables and figures included), which turns the current word count into a live
page estimate and tells how many words fit in the limit.
"""
from __future__ import annotations

import json
import re
import zlib
from pathlib import Path
from typing import Any

from .config import WorkbenchConfig
from .formats import strip_citations

RE_COUNT = re.compile(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)|/Count\s+(\d+)[^>]*?/Type\s*/Pages\b", re.S)
RE_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
RE_SKIP = re.compile(r"^\s*(?:#{1,6}\s|\|[\s:|-]+\|\s*$|!\[)")


def pdf_page_count(data: bytes) -> int | None:
    """Page count from the page-tree root, also inside compressed object streams (stdlib only)."""
    best = 0
    chunks = [data]
    for m in RE_STREAM.finditer(data):
        try:
            chunks.append(zlib.decompress(m.group(1)))
        except Exception:
            continue
    for c in chunks:
        for m in RE_COUNT.finditer(c):
            best = max(best, int(m.group(1) or m.group(2)))
    return best or None


def page_target(cfg: WorkbenchConfig, chapter: int) -> tuple[int, int] | None:
    if chapter in cfg.page_targets:
        return cfg.page_targets[chapter]
    if 0 in cfg.page_targets:
        return cfg.page_targets[0]
    if cfg.page_limit:
        return (0, int(cfg.page_limit))
    return None


def pdf_path(cfg: WorkbenchConfig, chapter: int) -> Path | None:
    if not cfg.pages_pdf:
        return None
    p = cfg.workspace / cfg.pages_pdf.format(chapter=chapter)
    return p if p.is_file() else None


def compiled_pages(cfg: WorkbenchConfig, chapter: int, sources: list[Path]) -> dict[str, Any]:
    newest = max((p.stat().st_mtime for p in sources), default=0)
    if cfg.pages_aux and cfg.pages_aux_label:
        aux = cfg.workspace / cfg.pages_aux.format(chapter=chapter)
        if aux.is_file():
            m = re.search(rf"\\newlabel\{{{re.escape(cfg.pages_aux_label)}\}}\{{\{{[^}}]*\}}\{{(\d+)\}}",
                          aux.read_text(encoding="utf-8", errors="replace"))
            if m:
                return {"pages": int(m.group(1)), "stale": aux.stat().st_mtime < newest, "at": aux.stat().st_mtime}
    pdf = pdf_path(cfg, chapter)
    if pdf:
        return {"pages": pdf_page_count(pdf.read_bytes()), "stale": pdf.stat().st_mtime < newest, "at": pdf.stat().st_mtime}
    return {"pages": None, "stale": True, "at": None}


def _records_path(cfg: WorkbenchConfig) -> Path:
    return cfg.workspace / ".thesis" / "pages.json"


def record_compile(cfg: WorkbenchConfig, chapter: int, words: int, pages: int | None) -> None:
    p = _records_path(cfg)
    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    data[str(chapter)] = {"words": words, "pages": pages}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def citation_share(texts: list[str]) -> float:
    """Share of the body characters taken by in-text citations (headings and table rules excluded)."""
    total = cites = 0
    for t in texts:
        body = "\n".join(l for l in re.sub(r"<!--.*?-->|```.*?```", " ", t, flags=re.S).splitlines()
                         if l.strip() and not RE_SKIP.match(l))
        n = len(" ".join(body.split()))
        total += n
        cites += max(0, n - len(" ".join(strip_citations(body).split())))
    return cites / total if total else 0.0


def budget(cfg: WorkbenchConfig, chapter: int, words: int, texts: list[str], sources: list[Path]) -> dict[str, Any]:
    target = page_target(cfg, chapter)
    comp = compiled_pages(cfg, chapter, sources)
    share = citation_share(texts)
    out: dict[str, Any] = {"target": list(target) if target else None, "pdf_pages": comp["pages"],
                           "stale": comp["stale"], "citation_share": round(share, 3), "words": words}
    P = comp["pages"]
    if not P:
        return out
    rec = {}
    p = _records_path(cfg)
    if p.is_file():
        try:
            rec = json.loads(p.read_text(encoding="utf-8")).get(str(chapter), {})
        except Exception:
            rec = {}
    words_then = rec.get("words") if rec.get("pages") == P and rec.get("words") else words
    sans = P * (1 - share)
    wpp = words_then / sans if sans else 0
    out.update({
        "pages_sans_citations": round(sans, 1),
        "words_per_page": round(wpp),
        "estimate_now": round(words / wpp, 1) if wpp else None,
        "words_fit": round(wpp * target[1], -1) if wpp and target else None,
        "words_from_record": bool(rec.get("pages") == P and rec.get("words")),
    })
    return out


def thesis_budgets(cfg: WorkbenchConfig, chapters, adapter) -> dict[int, dict[str, Any]]:
    """Budgets for every chapter. Drafts (few pages) borrow the median words-per-page of full chapters."""
    out = {c.number: budget(cfg, c.number, c.words, [s.content for s in c.sections], adapter.sources_for(c.number))
           for c in chapters}
    solid = sorted(b["words_per_page"] for b in out.values() if b.get("words_per_page") and b["pdf_pages"] >= 8)
    if solid:
        median = solid[len(solid) // 2]
        for b in out.values():
            if b.get("pdf_pages") and b["pdf_pages"] < 8:
                b["words_per_page"] = median
                b["estimate_now"] = max(round(b["words"] / median, 1), b["pages_sans_citations"])
                b["words_fit"] = round(median * b["target"][1], -1) if b["target"] else None
                b["draft"] = True
    return out
