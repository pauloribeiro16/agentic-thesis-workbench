"""Core structure & formatting checks (language-neutral)."""
from __future__ import annotations

import re

from ..formats import strip_citations
from ..quality import RE_BOLD_LINE, RE_CAPTION, RE_HEAD, RE_NUM_HEAD, RE_SEP

PLUGIN = {"id": "builtin.core", "version": "1.0", "api_version": 1,
          "description": "Budgets, placeholders, headings, cross-references, captions, numbering, HTML, bold."}

RE_PLACE = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b|\?\?|\[\.\.\.\]")
RE_HTML = re.compile(r"<(?:mark|span|u|font|div)\b[^>]*>", re.I)
RE_REF = re.compile(r"\b(Table|Figure)s?\s+(\d+)\.(\d+)")
RE_SEC = re.compile(r"\bSections?\s+(\d+)\.(\d+)")
RE_CH = re.compile(r"\bChapters?\s+(\d{1,2})\b")
RE_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
RE_FENCE = re.compile(r"```.*?```", re.S)


def register(reg) -> None:
    @reg.check("sections", group="Structure", label="Section count", rule="Sections per chapter — the author's plan")
    def sections(ctx, ch):
        exp = ctx.cfg.sections_for(ch.number)
        if exp is None:
            return {"state": "ok", "count": len(ch.sections), "note": "not configured"}
        return {"state": "ok" if len(ch.sections) == exp else "warn", "count": len(ch.sections), "note": f"expected {exp}"}

    @reg.check("placeholder", group="Structure", label="Unfinished text", rule="No TODO/TBD/FIXME/?? in final text", fail="bad")
    def placeholder(ctx, ch):
        extra = ctx.option("placeholder_words", [])
        rx = re.compile(RE_PLACE.pattern + "".join(rf"|\b{re.escape(w)}\b" for w in extra), re.I)
        return [s.item(i + 1, m.group(0)) for s in ctx.sections[ch.number]
                for i, l in enumerate(s.lines) if s.kinds[i] != "fence" for m in rx.finditer(l)]

    @reg.check("stacked", group="Structure", label="Heading straight after heading",
               rule="Introduce a section before opening a sub-section", fail="bad")
    def stacked(ctx, ch):
        out = []
        for s in ctx.sections[ch.number]:
            for i, l in enumerate(s.lines):
                if s.kinds[i] == "heading":
                    nxt = s.neighbour(i, 1).strip()
                    if nxt and (RE_HEAD.match(nxt) or RE_BOLD_LINE.match(nxt)):
                        out.append(s.item(i + 1, nxt[:80]))
        return out

    @reg.check("dangling", group="Structure", label="References to missing items",
               rule="Every 'Table/Figure/Section X.Y' must exist", fail="bad")
    def dangling(ctx, ch):
        out, known = [], ctx.known_refs
        for s in ctx.sections[ch.number]:
            for no, line in s.rows("prose", "list", "table"):
                said = strip_citations(line)
                for m in RE_REF.finditer(said):
                    if (m.group(1), int(m.group(2)), int(m.group(3))) not in known:
                        out.append(s.item(no, m.group(0)))
                for m in RE_SEC.finditer(said):
                    if ("Section", int(m.group(1)), int(m.group(2))) not in known:
                        out.append(s.item(no, m.group(0)))
        return out

    @reg.check("forward", group="Structure", label="Forward references",
               rule="Refer ahead only in introductions and conclusions ([quality.options] forward_allowed)")
    def forward(ctx, ch):
        allowed = {int(k): {int(x) for x in v} for k, v in (ctx.option("forward_allowed", {}) or {}).items()}
        out = []
        if ch.number <= 1:
            return out
        for s in ctx.sections[ch.number]:
            if s.is_conclusion or s.index == 1:
                continue
            for no, line in s.rows("prose", "list"):
                said = strip_citations(line)
                for m in RE_SEC.finditer(said):
                    ref = (int(m.group(1)), int(m.group(2)))
                    if ("Section",) + ref in ctx.known_refs and ref > s.num:
                        out.append(s.item(no, m.group(0)))
                for m in RE_CH.finditer(said):
                    n = int(m.group(1))
                    if n > ch.number and n not in allowed.get(ch.number, set()):
                        out.append(s.item(no, m.group(0)))
        return out

    @reg.check("table_caption", group="Formatting", label="Tables without caption",
               rule="Each table has a 'Table X.Y:' caption", fail="bad")
    def table_caption(ctx, ch):
        out = []
        for s in ctx.sections[ch.number]:
            i = 0
            while i < len(s.lines):
                if s.kinds[i] == "table" and i + 1 < len(s.lines) and RE_SEP.match(s.lines[i + 1]):
                    j = i
                    while j + 1 < len(s.lines) and s.kinds[j + 1] == "table":
                        j += 1
                    near = [s.neighbour(i, -1), s.neighbour(j, 1)]
                    if not any((m := RE_CAPTION.match(x)) and m.group(1) == "Table" for x in near):
                        out.append(s.item(i + 1))
                    i = j
                i += 1
        return out

    @reg.check("figure_caption", group="Formatting", label="Figures without caption",
               rule="Each image or diagram has a 'Figure X.Y:' caption", fail="bad")
    def figure_caption(ctx, ch):
        out = []
        for s in ctx.sections[ch.number]:
            spans = [(s.raw[:m.start()].count("\n"), s.raw[:m.end()].count("\n"))
                     for m in RE_FENCE.finditer(s.raw) if m.group(0).startswith("```mermaid")]
            spans += [(no - 1, no - 1) for no, _ in s.rows("image")]
            for a, b in spans:
                near = [s.neighbour(a, -1), s.neighbour(b, 1)]
                if not any((c := RE_CAPTION.match(x)) and c.group(1) == "Figure" for x in near):
                    out.append(s.item(a + 1, "figure"))
        return out

    @reg.check("numbering", group="Formatting", label="Numbering out of order",
               rule="Tables and figures numbered <chapter>.<n> in order", fail="bad")
    def numbering(ctx, ch):
        out, order = [], {"Table": 0, "Figure": 0}
        for s in ctx.sections[ch.number]:
            for no, line in s.rows("caption"):
                m = RE_CAPTION.match(line)
                name, a, b = m.group(1), int(m.group(2)), int(m.group(3))
                order[name] += 1
                if a != ch.number or b != order[name]:
                    out.append(s.item(no, f"expected {name} {ch.number}.{order[name]}"))
        return out

    @reg.check("float_ref", group="Formatting", label="Tables or figures not introduced",
               rule="Mention a table/figure in the text before it appears")
    def float_ref(ctx, ch):
        secs = ctx.sections[ch.number]
        out = []
        for si, s in enumerate(secs):
            for no, line in s.rows("caption"):
                m = RE_CAPTION.match(line)
                key = (m.group(1), int(m.group(2)), int(m.group(3)))
                first = None
                for t, other in enumerate(secs):
                    for n, x in other.rows("prose", "list"):
                        if any((r.group(1), int(r.group(2)), int(r.group(3))) == key for r in RE_REF.finditer(x)):
                            first = (t, n)
                            break
                    if first:
                        break
                if not first:
                    out.append(s.item(no, "never referenced"))
                elif first > (si, no):
                    out.append(s.item(no, "referenced only after it appears"))
        return out

    @reg.check("html", group="Formatting", label="HTML tags in the text", rule="No raw <mark>/<span>/<u> in the manuscript", fail="bad")
    def html(ctx, ch):
        return [s.item(no, RE_HTML.search(l).group(0)) for s in ctx.sections[ch.number]
                for no, l in s.rows("prose", "list", "table", "caption") if RE_HTML.search(l)]

    @reg.check("bold", group="Formatting", label="Bold outside the rule",
               rule="Bold only for run-in labels (ending in a full stop) and a term's first use")
    def bold(ctx, ch):
        out, seen = [], {}
        for s in ctx.sections[ch.number]:
            for no, line in s.rows("prose", "list"):
                if RE_BOLD_LINE.match(line.strip()):
                    continue
                for m in RE_BOLD.finditer(line):
                    inner = m.group(1).strip()
                    after = line[m.end():].lstrip()
                    is_label = re.fullmatch(r"\s*(?:[-*+]\s+|\d+\.\s+)?", line[:m.start()]) and not (after and after[0].islower())
                    if is_label:
                        if not inner.endswith((".", ":")):
                            out.append(s.item(no, f"label without full stop: {inner[:40]}"))
                        continue
                    k = inner.lower().rstrip(".:")
                    if k in seen:
                        out.append(s.item(no, f"already highlighted in {seen[k]}: {inner[:40]}"))
                    else:
                        seen[k] = s.path
        return out
