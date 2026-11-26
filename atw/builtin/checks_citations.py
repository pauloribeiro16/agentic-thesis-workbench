"""Citation checks: resolution, verified passages, problems, ordering."""
from __future__ import annotations

import re

PLUGIN = {"id": "builtin.citations", "version": "1.0", "api_version": 1,
          "description": "Every citation resolves to a work and is backed by a verified passage."}

YEAR = r"(?:19|20)\d{2}[a-z]?"
RE_MULTI = re.compile(rf"\(([^()]*{YEAR}(?:;\s*[^()]*{YEAR})+)\)")


def _item(u, detail=""):
    return {"file": u["file"], "line": u["line"], "text": u["text"], "detail": detail or u["cite"]}


def register(reg) -> None:
    @reg.check("cite_unresolved", group="Citations", label="Citations without a bibliography entry",
               rule="Each citation maps to one work in the bibliography", pack="citations")
    def cite_unresolved(ctx, ch):
        return [_item(u) for u in ctx.citation_uses[ch.number] if not u["key"]]

    @reg.check("cite_verified", group="Citations", label="Citations without a verified passage",
               rule="Cite only sources whose supporting passage was verified (ledger)", pack="citations")
    def cite_verified(ctx, ch):
        if not ctx.citations.ledger:
            return {"state": "na", "note": "no passage ledger yet"}
        return [_item(u) for u in ctx.citation_uses[ch.number] if not u["verified"]]

    @reg.check("cite_problem", group="Citations", label="Passages with a problem",
               rule="Verdict partial/does_not_support, or the source passage changed", pack="citations", fail="bad")
    def cite_problem(ctx, ch):
        return [_item(u) for u in ctx.citation_uses[ch.number] if u["problem"]]

    @reg.check("cite_order", group="Citations", label="Multiple citations out of order",
               rule="Alphabetical order inside one parenthesis ([quality.options] cite_order = 'alpha'|'none')",
               pack="citations")
    def cite_order(ctx, ch):
        if ctx.option("cite_order", "alpha") == "none":
            return []
        out = []
        for s in ctx.sections[ch.number]:
            for no, line in s.rows("prose", "list", "table"):
                for m in RE_MULTI.finditer(line):
                    parts = [x.strip().lower() for x in m.group(1).split(";")]
                    if parts != sorted(parts):
                        out.append(s.item(no, m.group(1)[:70]))
        return out
