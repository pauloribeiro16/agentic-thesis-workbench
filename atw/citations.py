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
        from .plugins import load_registry

        entries: list[dict[str, Any]] = []
        provider = load_registry(self.cfg).citation_providers.get(self.cfg.citation_provider)
        src = (self.cfg.csl_file or "references.json") if self.cfg.citation_provider in ("csl-json", "zotero", "mendeley") \
            else self.cfg.bib_file
        if provider and src and (ws / src).is_file():
            entries = provider((ws / src).read_text(encoding="utf-8", errors="ignore"))
            for e in entries:
                e["author"], e["title"] = delatex(e.get("author", "")), delatex(e.get("title", ""))

        lib = ws / self.cfg.library_dir if self.cfg.library_dir else None
        skip = set(self.cfg.raw.get("citations", {}).get("library_skip", []))
        lib_keys: dict[str, dict[str, Any]] = {}
        if lib and lib.is_dir():
            for d in lib.rglob("*"):
                if d.is_dir() and not d.name.startswith(("_", ".")) and d.name not in skip:
                    has_pdf = any(d.glob("*.pdf"))
                    has_md = (d / "full_text.md").is_file() or any(d.glob("*.md"))
                    if has_pdf or has_md:
                        lib_keys[d.name] = {"has_pdf": has_pdf, "has_fulltext": has_md, "dir": str(d.relative_to(ws))}

        ledger = self.load_ledger()
        verdicts_by_key: dict[str, list[str]] = {}
        for row in ledger.get("entries", []):
            k = row.get("key") or row.get("work") or ""
            if k:
                verdicts_by_key.setdefault(k, []).append(row_verdict(row))

        for e in entries:
            lk = lib_keys.get(e["key"], {})
            e["has_pdf"] = lk.get("has_pdf", False)
            e["has_fulltext"] = lk.get("has_fulltext", False)
            e["library_dir"] = lk.get("dir", "")
            vs = verdicts_by_key.get(e["key"], [])
            e["verified_passages"] = len([v for v in vs if v == "supports"])
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


# --- verdicts, passage integrity and citation uses -------------------------------------------------

VERDICT_ALIASES = {"apoia": "supports", "parcial": "partial", "nao_apoia": "does_not_support",
                   "não_apoia": "does_not_support"}
RE_NARRATIVE = re.compile(rf"\b([A-ZÀ-Ý][\w'’\-]+(?:\s+(?:and|&|et al\.)\s*[A-ZÀ-Ý]?[\w'’\-]*)?)\s+\(({YEAR})\)")


def row_verdict(row: dict[str, Any]) -> str:
    v = row.get("verdict") or (row.get("agent") or {}).get("verdict") or "unverified"
    return VERDICT_ALIASES.get(str(v), str(v))


RE_TEX_ACCENT = re.compile(r"""\\['`^"~=.uvHck]\s*\{?([A-Za-z])\}?""")


def delatex(s: str) -> str:
    """Drop LaTeX accent commands and braces (Hajri{\\'c} -> Hajric); matching is accent-insensitive anyway."""
    return RE_TEX_ACCENT.sub(r"\1", s).replace("{", "").replace("}", "")


def _fold(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def _plain(s: str) -> str:
    return " ".join(re.sub(r"[*_`]", "", str(s)).split())


class CitationIndex:
    """Resolves in-text citations to bibliography keys and ledger evidence for one workspace."""

    def __init__(self, svc: "CitationService") -> None:
        self.cfg = svc.cfg
        self.entries = svc.load_entries()
        self.keys = {e["key"].lower(): e["key"] for e in self.entries}
        self.by_author_year: dict[tuple[str, str], str] = {}
        for e in self.entries:
            author = delatex(e.get("author", "")).strip()
            first_author = author.split(" and ")[0].strip()
            surname = first_author.split(",")[0].strip().split(" ")[-1] if "," in first_author else (first_author.split(" ")[-1] if first_author else "")
            if surname and e.get("year"):
                self.by_author_year.setdefault((_fold(surname), str(e["year"])), e["key"])
        self.no_year = {str(k) for k in self.cfg.raw.get("citations", {}).get("no_year_keys", [])}
        self.ledger = [dict(r, verdict=row_verdict(r)) for r in svc.load_ledger().get("entries", [])]
        self._src_cache: dict[str, str] = {}

    def resolve(self, cite: str) -> str | None:
        alias = self.cfg.citation_aliases.get(cite.lower())
        if alias:
            return alias
        if cite in self.no_year:
            return cite
        if cite.lower() in self.keys:
            return self.keys[cite.lower()]
        m = re.match(rf"^(.+?),?\s*\(?({YEAR}|n\.d\.)\)?", cite)
        if m:
            surname = re.split(r"\s+(?:and|&|et)\s+|,", m.group(1).strip())[0].split(" ")[-1]
            return self.by_author_year.get((_fold(surname), m.group(2)))
        return None

    def uses_in(self, rel_file: str, text: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for no, line in enumerate(text.splitlines(), 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cites = extract_citations(line, self.cfg.citation_syntax)
            if self.cfg.citation_syntax == "author-year":
                cites += [f"{m.group(1)}, {m.group(2)}" for m in RE_NARRATIVE.finditer(line)]
                for m in RE_PAREN.finditer(line):
                    for part in m.group(0)[1:-1].split(";"):
                        head = part.strip().split(",")[0].strip()
                        if head in self.no_year:
                            cites.append(head)
            seen: set[str] = set()
            for c in cites:
                if c in seen:
                    continue
                seen.add(c)
                key = self.resolve(c)
                ev = [r for r in self.ledger if r.get("file") == rel_file and key and r.get("key") == key
                      and _plain(r.get("claim", ""))[:60] in _plain(line)]
                states = [self.passage_state(r) for r in ev]
                out.append({"file": rel_file, "line": no, "cite": c, "key": key,
                            "evidence": bool(ev),
                            "verified": bool(ev) and all(r["verdict"] == "supports" for r in ev)
                            and all(s == "ok" for s in states),
                            "problem": any(r["verdict"] in ("partial", "does_not_support") for r in ev)
                            or any(s == "altered" for s in states),
                            "text": line.strip()[:260]})
        return out

    def _source_text(self, ref: str) -> str:
        if ref in self._src_cache:
            return self._src_cache[ref]
        p = (self.cfg.workspace / self.cfg.library_dir / ref[4:]) if ref.startswith("lit:") else self.cfg.workspace / ref
        txt = p.read_text(encoding="utf-8", errors="ignore") if p.is_file() else ""
        self._src_cache[ref] = txt
        return txt

    def passage_state(self, row: dict[str, Any]) -> str:
        """ok | altered | no_source | no_anchor — detects when a verified passage no longer matches its source."""
        if not row.get("source"):
            return "no_source"
        if row.get("start") is None or not row.get("sha256"):
            return "no_anchor"
        text = self._source_text(row["source"])
        if not text:
            return "no_source"
        passage = text[int(row["start"]):int(row["end"])]
        return "ok" if fingerprint(passage) == row["sha256"] else "altered"


# --- work-level checks: does the archived source match its entry? is it sealed? ----------------------

_HASH_CACHE: dict[str, tuple[int, int, str]] = {}


def _sha_file(path: Path) -> str:
    st = path.stat()
    hit = _HASH_CACHE.get(str(path))
    if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
        return hit[2]
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    _HASH_CACHE[str(path)] = (st.st_size, st.st_mtime_ns, h.hexdigest())
    return h.hexdigest()


def title_match(title: str, text: str) -> float:
    """Share of the entry's title words found in the first pages of the source (an indication, not a proof)."""
    words = {w for w in re.findall(r"[a-z0-9]+", _fold(delatex(title))) if len(w) > 3}
    if not words:
        return 0.0
    head = " ".join(re.findall(r"[a-z0-9]+", _fold(text[:12000])))
    return sum(1 for w in words if f" {w} " in f" {head} ") / len(words)


def enrich_works(cfg: WorkbenchConfig, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Adds `match` (confirmed | doubtful | mismatch | no_text | no_source) and `seal` (intact | changed |
    not_sealed) to each entry. The seal uses `[citations] integrity_manifest` when configured."""
    ws = cfg.workspace
    manifest = {}
    man_rel = str(cfg.raw.get("citations", {}).get("integrity_manifest", ""))
    if man_rel and (ws / man_rel).is_file():
        try:
            manifest = json.loads((ws / man_rel).read_text(encoding="utf-8")).get("works", {})
        except Exception:
            manifest = {}
    lib = ws / cfg.library_dir if cfg.library_dir else None
    for e in entries:
        folder = ws / e["library_dir"] if e.get("library_dir") else None
        if not folder or not folder.is_dir():
            e["match"], e["match_score"] = "no_source", None
        else:
            texts = [folder / "full_text.md"] if (folder / "full_text.md").is_file() else \
                [p for p in sorted(folder.glob("*.md")) if not p.name.startswith("00_")]
            text = texts[0].read_text(encoding="utf-8", errors="ignore") if texts else ""
            if not text.strip():
                e["match"], e["match_score"] = "no_text", None
            else:
                sc = title_match(e.get("title", ""), text)
                e["match_score"] = round(sc, 2)
                e["match"] = "confirmed" if sc >= 0.7 else "doubtful" if sc >= 0.4 else "mismatch"
        if manifest:
            w = manifest.get(e["key"])
            if not w:
                e["seal"] = "not_sealed"
            else:
                bad = 0
                for rel, meta in (w.get("files") or {}).items():
                    f = (lib / rel) if lib else ws / rel
                    if not f.is_file() or _sha_file(f) != meta.get("sha256"):
                        bad += 1
                e["seal"] = "changed" if bad else "intact"
    keys = ("confirmed", "doubtful", "mismatch", "no_text", "no_source")
    return {
        "match": {k: sum(1 for e in entries if e.get("match") == k) for k in keys},
        "seal": {k: sum(1 for e in entries if e.get("seal") == k) for k in ("intact", "changed", "not_sealed")}
        if manifest else None,
        "passages": sum(1 for e in entries if e.get("verified_passages")),
    }
