"""Reference-manager connectors: Zotero and Mendeley.

`atw library sync` (or *Sync* in the Literature view) fetches the library, writes it as CSL-JSON to
`[citations] csl_file` — the bibliography the workbench reads — and, when `bib_export` is set, as BibTeX for
LaTeX. Nothing is sent anywhere: the workbench only reads from the reference manager.

    [citations]
    provider = "zotero"                # zotero | mendeley (read csl_file after a sync)
    csl_file = "references.json"
    bib_export = "latex/references.bib"   # optional, for the LaTeX base

    [citations.zotero]
    mode = "local"                     # local: Zotero 7 running on this computer (Settings → Advanced →
                                       #        "Allow other applications on this computer to communicate with Zotero")
                                       # web:   api.zotero.org with an API key
    library_type = "user"              # user | group
    library_id = ""                    # web mode: your numeric user id or the group id
    collection = ""                    # optional collection key (e.g. "ABCD1234")
    api_key_env = "ZOTERO_API_KEY"     # web mode: the key is read from this environment variable

    [citations.mendeley]
    mode = "file"                      # file: a BibTeX or RIS export from Mendeley Reference Manager
                                       # api:  api.mendeley.com with an OAuth access token
    file = "mendeley.bib"
    folder_id = ""                     # api mode, optional
    token_env = "MENDELEY_ACCESS_TOKEN"

Keys and tokens are never written to the thesis: they come from the environment, or from
`~/.config/agentic-thesis-workbench/credentials.toml` (`[zotero] api_key`, `[mendeley] access_token`).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import tomllib
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .citations import _parse_bibtex
from .config import WorkbenchConfig

SOURCES = ("zotero", "mendeley")
CREDENTIALS = Path.home() / ".config" / "agentic-thesis-workbench" / "credentials.toml"
ZOTERO_LOCAL = "http://127.0.0.1:23119/api"
ZOTERO_WEB = "https://api.zotero.org"
MENDELEY_API = "https://api.mendeley.com"
USER_AGENT = "agentic-thesis-workbench"

# fetch(url, headers) -> (status, headers, body bytes); replaceable in tests
Fetch = Callable[[str, dict[str, str]], tuple[int, dict[str, str], bytes]]


class LibraryError(RuntimeError):
    pass


def _http(url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read()
    except urllib.error.URLError as e:
        raise LibraryError(f"cannot reach {urllib.parse.urlsplit(url).netloc}: {e.reason}") from e


def _secret(env_name: str, section: str, key: str) -> str:
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    if CREDENTIALS.is_file():
        try:
            return str(tomllib.loads(CREDENTIALS.read_text(encoding="utf-8")).get(section, {}).get(key, ""))
        except Exception:
            return ""
    return ""


def settings(cfg: WorkbenchConfig) -> dict[str, Any]:
    cit = cfg.raw.get("citations", {})
    source = str(cit.get("sync_from") or (cfg.citation_provider if cfg.citation_provider in SOURCES else ""))
    return {"source": source, "csl_file": cfg.csl_file or "references.json",
            "bib_export": str(cit.get("bib_export") or ""),
            "zotero": dict(cit.get("zotero") or {}), "mendeley": dict(cit.get("mendeley") or {})}


# --- Zotero -------------------------------------------------------------------------------------------------

def fetch_zotero(opts: dict[str, Any], fetch: Fetch = _http) -> list[dict[str, Any]]:
    mode = str(opts.get("mode") or "local")
    ltype = "groups" if str(opts.get("library_type") or "user") == "group" else "users"
    if mode == "local":
        base, headers = f"{ZOTERO_LOCAL}/{ltype}/{opts.get('library_id') or 0}", {}
    elif mode == "web":
        lid = str(opts.get("library_id") or "")
        if not lid:
            raise LibraryError("Zotero web mode needs [citations.zotero] library_id (your user id or the group id)")
        key = _secret(str(opts.get("api_key_env") or "ZOTERO_API_KEY"), "zotero", "api_key")
        if not key:
            raise LibraryError("Zotero web mode needs an API key in ZOTERO_API_KEY (zotero.org/settings/keys)")
        base, headers = f"{ZOTERO_WEB}/{ltype}/{lid}", {"Zotero-API-Key": key, "Zotero-API-Version": "3"}
    else:
        raise LibraryError(f"unknown Zotero mode '{mode}' (local | web)")
    path = f"/collections/{opts['collection']}/items/top" if opts.get("collection") else "/items/top"
    items: list[dict[str, Any]] = []
    start = 0
    while True:
        url = f"{base}{path}?format=csljson&limit=100&start={start}"
        status, hdrs, body = fetch(url, headers)
        if status == 403 and mode == "local":
            raise LibraryError("Zotero refused the request: enable Settings → Advanced → 'Allow other applications "
                               "on this computer to communicate with Zotero'")
        if status != 200:
            raise LibraryError(f"Zotero answered {status}: {body[:200].decode('utf-8', 'replace')}")
        data = json.loads(body or b"[]")
        page = data.get("items", []) if isinstance(data, dict) else data
        items += [i for i in page if isinstance(i, dict) and i.get("type") not in ("note", "attachment")]
        total = int(hdrs.get("total-results") or 0)
        start += 100
        if not page or start >= total:
            break
    return items


# --- Mendeley -----------------------------------------------------------------------------------------------

_MENDELEY_TYPES = {"journal": "article-journal", "book": "book", "book_section": "chapter",
                   "conference_proceedings": "paper-conference", "thesis": "thesis", "web_page": "webpage",
                   "report": "report", "working_paper": "report", "patent": "patent", "magazine_article": "article-magazine",
                   "newspaper_article": "article-newspaper", "generic": "article"}


def mendeley_to_csl(doc: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {"type": _MENDELEY_TYPES.get(str(doc.get("type")), "article"),
                            "title": doc.get("title") or ""}
    authors = [{"family": a.get("last_name", ""), "given": a.get("first_name", "")}
               for a in doc.get("authors") or [] if isinstance(a, dict)]
    if authors:
        item["author"] = authors
    if doc.get("year"):
        item["issued"] = {"date-parts": [[int(doc["year"])]]}
    for src, dst in (("source", "container-title"), ("volume", "volume"), ("issue", "issue"), ("pages", "page"),
                     ("publisher", "publisher"), ("abstract", "abstract")):
        if doc.get(src):
            item[dst] = str(doc[src])
    ids = doc.get("identifiers") or {}
    if ids.get("doi"):
        item["DOI"] = ids["doi"]
    if doc.get("websites"):
        item["URL"] = doc["websites"][0]
    if doc.get("citation_key"):
        item["citation-key"] = doc["citation_key"]
    return item


def fetch_mendeley(opts: dict[str, Any], workspace: Path, fetch: Fetch = _http) -> list[dict[str, Any]]:
    mode = str(opts.get("mode") or "file")
    if mode == "file":
        rel = str(opts.get("file") or "")
        p = (workspace / rel) if rel else None
        if not p or not p.is_file():
            raise LibraryError("Mendeley file mode needs [citations.mendeley] file: a BibTeX or RIS export "
                               "(Mendeley Reference Manager → File → Export)")
        text = p.read_text(encoding="utf-8", errors="ignore")
        return ris_to_csl(text) if p.suffix.lower() == ".ris" or text.lstrip().startswith("TY  -") else bibtex_to_csl(text)
    if mode != "api":
        raise LibraryError(f"unknown Mendeley mode '{mode}' (file | api)")
    token = _secret(str(opts.get("token_env") or "MENDELEY_ACCESS_TOKEN"), "mendeley", "access_token")
    if not token:
        raise LibraryError("Mendeley api mode needs an OAuth access token in MENDELEY_ACCESS_TOKEN")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.mendeley-document.1+json"}
    url = f"{MENDELEY_API}/documents?view=all&limit=500"
    if opts.get("folder_id"):
        url += f"&folder_id={urllib.parse.quote(str(opts['folder_id']))}"
    docs: list[dict[str, Any]] = []
    while url:
        status, hdrs, body = fetch(url, headers)
        if status == 401:
            raise LibraryError("Mendeley rejected the token (they expire after an hour): get a new one")
        if status != 200:
            raise LibraryError(f"Mendeley answered {status}: {body[:200].decode('utf-8', 'replace')}")
        docs += json.loads(body or b"[]")
        m = re.search(r'<([^>]+)>;\s*rel="next"', hdrs.get("link", ""))
        url = m.group(1) if m else ""
    return [mendeley_to_csl(d) for d in docs if isinstance(d, dict)]


# --- file formats -------------------------------------------------------------------------------------------

def _bib_author_list(s: str) -> list[dict[str, str]]:
    out = []
    for name in re.split(r"\s+and\s+", s.strip()):
        name = name.strip()
        if not name:
            continue
        if "," in name:
            fam, giv = (x.strip() for x in name.split(",", 1))
        else:
            parts = name.split()
            fam, giv = parts[-1], " ".join(parts[:-1])
        out.append({"family": fam, "given": giv})
    return out


_BIB_TYPES = {"article": "article-journal", "book": "book", "incollection": "chapter", "inbook": "chapter",
              "inproceedings": "paper-conference", "conference": "paper-conference", "phdthesis": "thesis",
              "mastersthesis": "thesis", "techreport": "report", "misc": "article", "online": "webpage"}


def bibtex_to_csl(text: str) -> list[dict[str, Any]]:
    items = []
    for e in _parse_bibtex(text):
        it: dict[str, Any] = {"id": e["key"], "citation-key": e["key"], "type": _BIB_TYPES.get(e["type"], "article"),
                              "title": e.get("title", "")}
        if e.get("author"):
            it["author"] = _bib_author_list(e["author"])
        if str(e.get("year", "")).isdigit():
            it["issued"] = {"date-parts": [[int(e["year"])]]}
        if e.get("venue"):
            it["container-title"] = e["venue"]
        if e.get("doi"):
            it["DOI"] = e["doi"]
        items.append(it)
    return items


_RIS_TYPES = {"JOUR": "article-journal", "BOOK": "book", "CHAP": "chapter", "CONF": "paper-conference",
              "CPAPER": "paper-conference", "THES": "thesis", "RPRT": "report", "ELEC": "webpage", "GEN": "article"}


def ris_to_csl(text: str) -> list[dict[str, Any]]:
    items, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])  - ?(.*)$", line)
        if not m:
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "TY":
            cur = {"type": _RIS_TYPES.get(val, "article"), "author": []}
        elif cur is None:
            continue
        elif tag == "ER":
            if not cur["author"]:
                cur.pop("author")
            items.append(cur)
            cur = None
        elif tag in ("AU", "A1"):
            cur["author"] += _bib_author_list(val)
        elif tag in ("TI", "T1"):
            cur["title"] = val
        elif tag in ("PY", "Y1", "DA") and "issued" not in cur and re.match(r"\d{4}", val):
            cur["issued"] = {"date-parts": [[int(val[:4])]]}
        elif tag in ("JO", "T2", "JF", "BT"):
            cur.setdefault("container-title", val)
        elif tag == "DO":
            cur["DOI"] = val
        elif tag == "UR":
            cur.setdefault("URL", val)
        elif tag == "PB":
            cur["publisher"] = val
        elif tag == "ID":
            cur["citation-key"] = val
    return items


# --- keys, BibTeX export and the sync itself -----------------------------------------------------------------

def _ascii(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode())


def assign_keys(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every item gets `id` = its citation key: the manager's own key when it has one (`citation-key`, e.g. from
    Better BibTeX or Mendeley), otherwise FamilyYear with a/b/c on clashes."""
    used: set[str] = set()
    out = []
    for it in items:
        it = dict(it)
        key = str(it.get("citation-key") or "")
        if not key:
            fam = ""
            for a in it.get("author") or []:
                fam = a.get("family") or a.get("literal") or ""
                break
            year = ""
            parts = (it.get("issued") or {}).get("date-parts") or [[]]
            if parts and parts[0]:
                year = str(parts[0][0])
            base = (_ascii(fam) or _ascii(str(it.get("title", "")).split(" ")[0]) or "ref") + year
            key, n = base, 0
            while key in used:
                n += 1
                key = base + "abcdefghijklmnopqrstuvwxyz"[(n - 1) % 26] * (1 + (n - 1) // 26)
        used.add(key)
        it["id"] = it["citation-key"] = key
        out.append(it)
    return out


_CSL_TO_BIB = {"article-journal": "article", "book": "book", "chapter": "incollection",
               "paper-conference": "inproceedings", "thesis": "phdthesis", "report": "techreport", "webpage": "misc"}


def _bib_escape(s: str) -> str:
    return re.sub(r"([&%$#_])", r"\\\1", str(s)).replace("\n", " ")


def csl_to_bibtex(items: list[dict[str, Any]]) -> str:
    out = ["% Written by atw library sync — edit the library in your reference manager, not this file.\n"]
    for it in items:
        etype = _CSL_TO_BIB.get(str(it.get("type")), "misc")
        f: list[tuple[str, str]] = []
        if it.get("author"):
            f.append(("author", " and ".join(
                f"{a.get('family', '')}, {a.get('given', '')}".strip(", ") if a.get("family") else a.get("literal", "")
                for a in it["author"])))
        f.append(("title", "{" + _bib_escape(it.get("title", "")) + "}"))
        parts = (it.get("issued") or {}).get("date-parts") or [[]]
        if parts and parts[0]:
            f.append(("year", str(parts[0][0])))
        ct = it.get("container-title")
        if ct:
            f.append(({"article": "journal", "incollection": "booktitle", "inproceedings": "booktitle"}.get(etype, "howpublished"), ct))
        for csl, bib in (("volume", "volume"), ("issue", "number"), ("page", "pages"), ("publisher", "publisher"),
                         ("DOI", "doi"), ("URL", "url")):
            if it.get(csl):
                f.append((bib, str(it[csl])))
        body = ",\n".join(f"  {k} = {{{v if k in ('title', 'url', 'doi') else _bib_escape(v)}}}" for k, v in f)
        out.append(f"@{etype}{{{it['id']},\n{body}\n}}\n")
    return "\n".join(out)


def sync(cfg: WorkbenchConfig, fetch: Fetch = _http) -> dict[str, Any]:
    st = settings(cfg)
    src = st["source"]
    if src == "zotero":
        raw = fetch_zotero(st["zotero"], fetch)
    elif src == "mendeley":
        raw = fetch_mendeley(st["mendeley"], cfg.workspace, fetch)
    else:
        raise LibraryError("no reference manager configured: set [citations] provider = \"zotero\" or \"mendeley\"")
    items = assign_keys(raw)
    ws = cfg.workspace
    csl = ws / st["csl_file"]
    csl.parent.mkdir(parents=True, exist_ok=True)
    csl.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written = [st["csl_file"]]
    if st["bib_export"]:
        bib = ws / st["bib_export"]
        bib.parent.mkdir(parents=True, exist_ok=True)
        bib.write_text(csl_to_bibtex(items), encoding="utf-8")
        written.append(st["bib_export"])
    meta = {"source": src, "mode": st[src].get("mode") or ("local" if src == "zotero" else "file"),
            "synced_at": dt.datetime.now().isoformat(timespec="seconds"), "count": len(items), "files": written}
    mp = ws / ".thesis" / "citations" / "library_sync.json"
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def last_sync(cfg: WorkbenchConfig) -> dict[str, Any]:
    p = cfg.workspace / ".thesis" / "citations" / "library_sync.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
