"""Thesis templates and the output base (LaTeX or Word).

A template is a folder with a `template.toml` manifest and one subfolder per base:

    <template>/template.toml
    <template>/latex/...          (main file with {{field}} placeholders)
    <template>/word/template.docx (optional — e.g. an institution's official Word model)

Templates come from the workbench (`atw/templates/`) and from the thesis (`.thesis/templates/`, which wins).
`thesis.toml` chooses one:

    [output]
    base = "latex"          # latex | word
    template = "uminho-phd"
    dir = "latex"           # where the thesis document lives

    [template]              # values for the template's fields; [project] gives author and title
    school = "School of Engineering"
    supervisor = "…"

Applying a template copies it into `[output] dir` once; later runs only refresh the generated parts (the main
file's fields and its chapter list for LaTeX, the document properties for Word) and never touch other files.
"""
from __future__ import annotations

import re
import shutil
import tomllib
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from .config import WorkbenchConfig

BUILTIN = Path(__file__).resolve().parent / "templates"
BASES = ("latex", "word")
_FIELD = re.compile(r"\{\{([a-z_]+)\}\}")
_LATEX_SPECIAL = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_"}


def template_dirs(cfg: WorkbenchConfig) -> list[Path]:
    return [BUILTIN, cfg.workspace / ".thesis" / "templates"]


def list_templates(cfg: WorkbenchConfig) -> dict[str, dict[str, Any]]:
    """id -> manifest (+ `path`, and `bases`: which bases are ready). Thesis templates override built-ins by id,
    but a base missing from the thesis copy (e.g. only word/ was added there) is taken from the built-in."""
    found: dict[str, dict[str, Any]] = {}
    for root in template_dirs(cfg):
        if not root.is_dir():
            continue
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            man = d / "template.toml"
            data: dict[str, Any] = tomllib.loads(man.read_text(encoding="utf-8")) if man.is_file() else {}
            tid = str(data.get("id") or d.name)
            prev = found.get(tid)
            entry = {**(prev or {}), **data, "id": tid}
            entry.setdefault("bases", {})
            paths = dict((prev or {}).get("paths", {}))
            for base, spec in (entry.get("bases") or {}).items():
                folder = d / str((spec or {}).get("dir", base))
                main = folder / str((spec or {}).get("main", ""))
                if folder.is_dir() and main.is_file():
                    paths[base] = str(folder)
            entry["paths"] = paths
            entry["ready"] = {b: b in paths for b in BASES}
            found[tid] = entry
    return found


def fields(cfg: WorkbenchConfig, manifest: dict[str, Any]) -> dict[str, str]:
    """The template's fields: its defaults, then [project] (author, title), then [template]."""
    out = {k: str(v) for k, v in (manifest.get("fields") or {}).items()}
    proj = cfg.raw.get("project", {})
    if proj.get("author"):
        out["author"] = str(proj["author"])
    title = str(proj.get("title") or "")
    if title and not any(k in cfg.raw.get("template", {}) for k in ("title_a", "title_b", "title_c")):
        a, b, c = split_title(title)
        out.update(title_a=a, title_b=b, title_c=c)
    for k, v in (cfg.raw.get("template") or {}).items():
        if isinstance(v, (str, int, float)):
            out[k] = str(v)
    return out


def split_title(title: str, width: int = 38) -> tuple[str, str, str]:
    """Up to three cover lines of about `width` characters, breaking at spaces."""
    lines, cur = [], ""
    for w in title.split():
        if cur and len(cur) + 1 + len(w) > width and len(lines) < 2:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    lines += ["", ""]
    return lines[0], lines[1], lines[2]


def latex_escape(s: str) -> str:
    return "".join(_LATEX_SPECIAL.get(ch, ch) for ch in s)


def render_latex(text: str, values: dict[str, str], chapters: list[str], bib_name: str) -> str:
    v = {k: latex_escape(x) for k, x in values.items()}
    v["area_line"] = f"\\area{{{v['area']}}}" if v.get("area") else "%\\area{Area of specialization}"
    v["cosupervisor_line"] = (f"\\cosupervisor{{{v['cosupervisor']}}}" if v.get("cosupervisor")
                              else "%\\cosupervisor{Co-supervisor}")
    v["chapters"] = "\n".join(f"\\input{{{c}}}" for c in chapters) or "% (no chapter files yet)"
    v["bib_name"] = bib_name
    return _FIELD.sub(lambda m: v.get(m.group(1), m.group(0)), text)


def _chapters(out: Path) -> list[str]:
    return [str(p.relative_to(out).with_suffix("")).replace("\\", "/")
            for p in sorted((out / "chapters").glob("*.tex"), key=lambda p: p.name)]


def _bib_name(out: Path) -> str:
    bibs = sorted(out.glob("*.bib"))
    return bibs[0].stem if bibs else "references"


def output_settings(cfg: WorkbenchConfig) -> dict[str, str]:
    o = cfg.raw.get("output", {})
    base = str(o.get("base") or "latex")
    return {"base": base, "template": str(o.get("template") or ""),
            "dir": str(o.get("dir") or ("latex" if base == "latex" else "word"))}


def status(cfg: WorkbenchConfig) -> dict[str, Any]:
    st = output_settings(cfg)
    tpls = list_templates(cfg)
    t = tpls.get(st["template"])
    out = cfg.workspace / st["dir"]
    spec = ((t or {}).get("bases") or {}).get(st["base"]) or {}
    main = out / str(spec.get("main", "")) if spec.get("main") else None
    if st["base"] == "word" and t:
        main = out / "thesis.docx"
    return {**st, "templates": [{"id": k, "name": v.get("name", k), "description": v.get("description", ""),
                                 "ready": v["ready"], "notes": {b: (v.get("bases") or {}).get(b, {}).get("notes", "")
                                                                for b in BASES}}
                                for k, v in sorted(tpls.items())],
            "applied": bool(main and main.is_file()), "main": str(main.relative_to(cfg.workspace)) if main else "",
            "fields": fields(cfg, t) if t else {}}


def apply(cfg: WorkbenchConfig, template: str | None = None, base: str | None = None,
          into: str | None = None) -> tuple[bool, str]:
    st = output_settings(cfg)
    tid, base = template or st["template"], base or st["base"]
    explicit_dir = cfg.raw.get("output", {}).get("dir")
    into = into or (st["dir"] if explicit_dir or base == st["base"] else ("latex" if base == "latex" else "word"))
    if base not in BASES:
        return False, f"unknown base '{base}' (latex | word)"
    tpls = list_templates(cfg)
    if not tid:
        return False, "no template chosen: set [output] template in thesis.toml (atw template list shows them)"
    if tid not in tpls:
        return False, f"unknown template '{tid}' (available: {', '.join(sorted(tpls)) or 'none'})"
    t = tpls[tid]
    if not t["ready"].get(base):
        note = ((t.get("bases") or {}).get(base) or {}).get("notes", "")
        return False, f"template '{tid}' has no {base} base yet. {note}".strip()
    src = Path(t["paths"][base])
    out = (cfg.workspace / into).resolve()
    if cfg.workspace.resolve() not in out.parents and out != cfg.workspace.resolve():
        return False, "the output folder must be inside the thesis"
    spec = t["bases"][base]
    values = fields(cfg, t)
    return (_apply_latex if base == "latex" else _apply_word)(src, out, spec, values, cfg)


def _apply_latex(src: Path, out: Path, spec: dict[str, Any], values: dict[str, str],
                 cfg: WorkbenchConfig) -> tuple[bool, str]:
    main_name = str(spec.get("main", "dissertation.tex"))
    created = 0
    has_chapters = any((out / "chapters").glob("*.tex"))
    has_bib = any(out.glob("*.bib"))
    for f in src.rglob("*"):
        if not f.is_file() or (f.parent == src and f.name == main_name):
            continue
        rel = f.relative_to(src)
        # Example files ship as "<name>.in" (e.g. references.bib.in) so a copy of the workbench carries no live
        # bibliography — theses often protect every .bib — and become "<name>" in the thesis.
        if f.suffix == ".in":
            rel = rel.with_suffix("")
        if (rel.parts[0] == "chapters" and has_chapters) or (rel.suffix == ".bib" and len(rel.parts) == 1 and has_bib):
            continue  # the example chapter and bibliography are only for a new thesis
        dest = out / rel
        if not dest.exists():  # never overwrite the author's files
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            created += 1
    master = (src / main_name).read_text(encoding="utf-8")
    main = out / main_name
    rendered = render_latex(master, values, _chapters(out), _bib_name(out))
    if main.is_file():
        # keep the author's edits: refresh only the generated chapter block
        cur = main.read_text(encoding="utf-8")
        block = re.search(r"%% ATW:CHAPTERS\n.*?%% /ATW:CHAPTERS", rendered, re.S)
        if block and "%% ATW:CHAPTERS" in cur:
            cur = re.sub(r"%% ATW:CHAPTERS\n.*?%% /ATW:CHAPTERS", lambda _: block.group(0), cur, flags=re.S)
            main.write_text(cur, encoding="utf-8")
            return True, f"{main.relative_to(cfg.workspace)}: chapter list refreshed ({created} new template files)"
        return True, f"{main.relative_to(cfg.workspace)} exists and has no ATW:CHAPTERS block — left as it is"
    main.write_text(rendered, encoding="utf-8")
    return True, f"created {main.relative_to(cfg.workspace)} and {created} template files"


def _apply_word(src: Path, out: Path, spec: dict[str, Any], values: dict[str, str],
                cfg: WorkbenchConfig) -> tuple[bool, str]:
    template = src / str(spec.get("main", "template.docx"))
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "thesis.docx"
    existed = dest.exists()
    base_doc = dest if existed else template
    tmp = dest.with_suffix(".docx.tmp")
    with zipfile.ZipFile(base_doc) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "docProps/core.xml":
                data = _core_props(data.decode("utf-8"), values).encode("utf-8")
            elif not existed and item.filename.startswith("word/") and item.filename.endswith(".xml"):
                text = data.decode("utf-8")
                text = _FIELD.sub(lambda m: xml_escape(values.get(m.group(1), m.group(0))), text)
                data = text.encode("utf-8")
            zout.writestr(item, data)
    tmp.replace(dest)
    rel = dest.relative_to(cfg.workspace)
    return True, f"{'updated the properties of' if existed else 'created'} {rel}"


def _core_props(xml: str, values: dict[str, str]) -> str:
    title = " ".join(x for x in (values.get("title_a"), values.get("title_b"), values.get("title_c")) if x)
    author = values.get("author", "")
    for tag, val in (("dc:title", title), ("dc:creator", author), ("cp:lastModifiedBy", author)):
        if not val:
            continue
        if re.search(rf"<{tag}\b[^>]*/>", xml):
            xml = re.sub(rf"<{tag}\b[^>]*/>", f"<{tag}>{xml_escape(val)}</{tag}>", xml)
        elif re.search(rf"<{tag}\b", xml):
            xml = re.sub(rf"(<{tag}\b[^>]*>).*?(</{tag}>)", lambda m: m.group(1) + xml_escape(val) + m.group(2), xml, flags=re.S)
        else:
            xml = xml.replace("</cp:coreProperties>", f"<{tag}>{xml_escape(val)}</{tag}></cp:coreProperties>")
    return xml
