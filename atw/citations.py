"""Pluggable citation & literature management (BibTeX + CSL-JSON + verified passage ledger)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .config import WorkbenchConfig

VERDICTS = ("supports", "partial", "does_not_support")
RE_BIB_ENTRY = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", re.S)
RE_PAREN = re.compile(r"\((?:[^()]|\([^()]*\))*\)")
YEAR = r"(?:19|20)\d{2}[a-z]?"
RE_AUTHOR_YEAR = re.compile(rf"^([A-ZÀ-Ý][^,;()]*?),\s*({YEAR}|n\.d\.)")
RE_PANDOC_CITE = re.compile(r"@([A-Za-z0-9_:\-\.]+)")
RE_LATEX_CITE = re.compile(r"\\(?:cite|parencite|textcite|citep|citet)\*?(?:\[[^\]]*\])*\{([^}]+)\}")


def _bib_field(entry: str, name: str) -> str:
    m = re.search(rf"(?:^|[,\s]){name}\s*=\s*([{{\"])", entry, re.I)
    if not m:
        m2 = re.search(rf"(?:^|[,\s]){name}\s*=\s*(\d+)", entry, re.I)
        return m2.group(1) if m2 else ""
    i = m.end()
    close = "}" if m.group(1) == "{" else '"'
    depth = 0
    buf: list[str] = []
    while i < len(entry):
        c = entry[i]
        if c == "{":
            depth += 1
        elif c == "}" and depth > 0:
            depth -= 1
        elif c == close and depth == 0:
            break
        buf.append(c)
        i += 1
    return re.sub(r"\s+", " ", "".join(buf)).strip()


def _parse_bibtex(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    matches = list(RE_BIB_ENTRY.finditer(text))
    for idx, m in enumerate(matches):
        etype = m.group(1).lower()
        if etype in ("comment", "preamble", "string"):
            continue
        key = m.group(2).strip()
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end]
        entries.append(
            {
                "key": key,
                "type": etype,
                "title": _bib_field(body, "title").replace("{", "").replace("}", ""),
                "author": _bib_field(body, "author").replace("{", "").replace("}", ""),
                "year": _bib_field(body, "year"),
                "venue": _bib_field(body, "journal") or _bib_field(body, "booktitle") or _bib_field(body, "publisher"),
                "doi": _bib_field(body, "doi"),
                "source_format": "bibtex",
            }
        )
    return entries


def _parse_csl_json(text: str) -> list[dict[str, Any]]:
    raw = json.loads(text)
    items = raw if isinstance(raw, list) else raw.get("items", [])
    entries: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        authors = []
        for a in item.get("author", []):
            if isinstance(a, dict):
                name = " ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("literal", "")
                if name:
                    authors.append(name)
        issued = item.get("issued", {})
        year = ""
        if isinstance(issued, dict):
            parts = issued.get("date-parts", [[]])
            if parts and parts[0]:
                year = str(parts[0][0])
        entries.append(
            {
                "key": str(item.get("id") or item.get("citation-key") or ""),
                "type": str(item.get("type") or "article"),
                "title": str(item.get("title") or ""),
                "author": ", ".join(authors),
                "year": year,
                "venue": str(item.get("container-title") or item.get("publisher") or ""),
                "doi": str(item.get("DOI") or ""),
                "source_format": "csl-json",
            }
        )
    return [e for e in entries if e["key"]]


def fingerprint(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def extract_citations(text: str, syntax: str = "author-year") -> list[str]:
    found: list[str] = []
    if syntax == "pandoc":
        found.extend(RE_PANDOC_CITE.findall(text))
    elif syntax == "latex":
        for group in RE_LATEX_CITE.findall(text):
            for k in group.split(","):
                if k.strip():
                    found.append(k.strip())
    else:
        for m in RE_PAREN.finditer(text):
            inner = m.group(0)[1:-1]
            for part in inner.split(";"):
                am = RE_AUTHOR_YEAR.match(part.strip())
                if am:
                    found.append(f"{am.group(1).strip()}, {am.group(2).strip()}")
    return found


class CitationService:
    """Normalizes BibTeX / CSL-JSON entries and resolves verified passage ledger."""

    def __init__(self, cfg: WorkbenchConfig) -> None:
        self.cfg = cfg

    def load_entries(self) -> list[dict[str, Any]]:
        ws = self.cfg.workspace
        entries: list[dict[str, Any]] = []
        if self.cfg.citation_provider == "csl-json" and self.cfg.csl_file:
            p = ws / self.cfg.csl_file
            if p.is_file():
                entries = _parse_csl_json(p.read_text(encoding="utf-8", errors="ignore"))
        elif self.cfg.bib_file:
            p = ws / self.cfg.bib_file
            if p.is_file():
                entries = _parse_bibtex(p.read_text(encoding="utf-8", errors="ignore"))

        lib = ws / self.cfg.library_dir if self.cfg.library_dir else None
        lib_keys: dict[str, dict[str, Any]] = {}
        if lib and lib.is_dir():
            for d in lib.rglob("*"):
                if d.is_dir() and d.name not in ("integrity", "_pdf_cache", "incoming", "__pycache__"):
                    has_pdf = any(d.glob("*.pdf"))
                    has_md = (d / "full_text.md").is_file() or any(d.glob("*.md"))
                    if has_pdf or has_md:
                        lib_keys[d.name] = {"has_pdf": has_pdf, "has_fulltext": has_md, "dir": str(d.relative_to(ws))}

        ledger = self.load_ledger()
        verdicts_by_key: dict[str, list[str]] = {}
        for row in ledger.get("entries", []):
            k = row.get("key") or row.get("work") or ""
            if k:
                verdicts_by_key.setdefault(k, []).append(row.get("verdict", "unverified"))

        for e in entries:
            lk = lib_keys.get(e["key"], {})
            e["has_pdf"] = lk.get("has_pdf", False)
            e["has_fulltext"] = lk.get("has_fulltext", False)
            e["library_dir"] = lk.get("dir", "")
            vs = verdicts_by_key.get(e["key"], [])
            e["verified_passages"] = len([v for v in vs if v in ("supports", "apoia")])
            e["status"] = "verified" if e["verified_passages"] > 0 else ("archived" if e["has_pdf"] or e["has_fulltext"] else "bib_only")

        return entries

    def load_ledger(self) -> dict[str, Any]:
        p = self.cfg.workspace / self.cfg.ledger_file
        if not p.is_file():
            return {"version": 1, "entries": []}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {"version": 1, "entries": []}

    def save_ledger(self, data: dict[str, Any]) -> None:
        p = self.cfg.workspace / self.cfg.ledger_file
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".ledger.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp, p)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
