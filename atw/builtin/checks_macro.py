"""Thesis-level (macro) and chapter-balance checks. They only use the author's plan when it exists."""
from __future__ import annotations

import re
from collections import defaultdict

PLUGIN = {"id": "builtin.macro", "version": "1.0", "api_version": 1,
          "description": "Structure against the plan, page balance, links between chapters, term variants across "
                         "chapters, overall citation verification, thesis-wide narrative review, section balance."}

RE_CH = re.compile(r"\bChapters?\s+(\d{1,2})\b|\bCap(?:ítulo|\.)\s*(\d{1,2})\b")
RE_HYPH = re.compile(r"\b([a-z]{3,})-([a-z]{3,})\b")


def _texts(ctx):
    return {n: "\n".join(s.raw for s in secs) for n, secs in ctx.sections.items()}


def register(reg) -> None:
    @reg.check("plan_structure", group="Thesis", label="Structure against your plan",
               rule="Every chapter in the plan exists, and every chapter found is in the plan", pack="thesis-level",
               scope="thesis", fail="bad")
    def plan_structure(ctx):
        planned = set(ctx.cfg.chapter_specs)
        if not planned:
            return {"state": "ok", "note": "no chapters in the plan"}
        found = {c.number for c in ctx.chapters}
        out = [{"file": ctx.cfg.plan_file, "line": 0, "text": ctx.cfg.spec(n).get("title", ""), "detail": f"Chapter {n} planned, not found"}
               for n in sorted(planned - found)]
        out += [{"file": "", "line": 0, "text": c.title, "detail": f"Chapter {c.number} not in the plan"}
                for c in ctx.chapters if c.number not in planned]
        return out

    @reg.check("page_balance", group="Thesis", label="Pages across chapters",
               rule="Each chapter within its page target (your plan)", pack="thesis-level", scope="thesis")
    def page_balance(ctx):
        from ..formats import get_adapter
        from ..pages import thesis_budgets
        b = thesis_budgets(ctx.cfg, ctx.chapters, get_adapter(ctx.cfg))
        out, total = [], 0.0
        for c in ctx.chapters:
            x = b[c.number]
            if not x.get("target") or not x.get("estimate_now"):
                continue
            total += x["estimate_now"]
            lo, hi = x["target"]
            if not lo <= x["estimate_now"] <= hi:
                out.append({"file": "", "line": 0, "text": c.title,
                            "detail": f"Chapter {c.number}: ≈ {x['estimate_now']} pages, target {lo}–{hi}"})
        return {"items": out, "note": f"≈ {round(total)} pages in total (without citations)"} if out else \
            {"state": "ok", "note": f"≈ {round(total)} pages in total (without citations)"}

    @reg.check("chapter_links", group="Thesis", label="Links between chapters",
               rule="From Chapter 2 on, each chapter refers back to at least one earlier chapter", pack="thesis-level",
               scope="thesis")
    def chapter_links(ctx):
        texts = _texts(ctx)
        out = []
        for c in ctx.chapters:
            if c.number <= 1 or len(texts.get(c.number, "")) < 2000:
                continue
            refs = {int(a or b) for a, b in RE_CH.findall(texts[c.number])}
            if not any(r < c.number for r in refs):
                out.append({"file": "", "line": 0, "text": c.title, "detail": f"Chapter {c.number} never refers to an earlier chapter"})
        return out

    @reg.check("term_variants", group="Thesis", label="Same term written differently across chapters",
               rule="A term written joined somewhere (lifecycle) and hyphenated or apart elsewhere (life-cycle, life cycle)",
               pack="thesis-level", scope="thesis")
    def term_variants(ctx):
        texts = {n: t.lower() for n, t in _texts(ctx).items()}
        words = {n: set(re.findall(r"[a-z]+", t)) for n, t in texts.items()}   # joined forms
        hyph = {n: set(RE_HYPH.findall(t)) for n, t in texts.items()}
        out = []
        for a, b in sorted({p for h in hyph.values() for p in h}):
            joined = [n for n, w in words.items() if a + b in w]
            if not joined:
                continue  # "border-control" vs "border control" is ordinary English
            used = {f"{a}-{b}": [n for n, h in hyph.items() if (a, b) in h], f"{a}{b}": joined,
                    f"{a} {b}": [n for n, t in texts.items() if re.search(rf"\b{a} {b}\b", t)]}
            used = {f: sorted(chs) for f, chs in used.items() if chs}
            if len(used) > 1:
                out.append({"file": "", "line": 0, "text": " · ".join(used),
                            "detail": "; ".join(f"'{f}' in Ch. {', '.join(map(str, chs))}" for f, chs in used.items())})
        return out

    @reg.check("citations_overall", group="Thesis", label="Citations verified across the thesis",
               rule="Share of in-text citations backed by a verified passage", pack="thesis-level", scope="thesis")
    def citations_overall(ctx):
        uses = [u for us in ctx.citation_uses.values() for u in us]
        if not uses or not ctx.citations.ledger:
            return {"state": "na", "note": "no passage ledger yet"}
        ok = sum(1 for u in uses if u["verified"])
        return {"state": "ok" if ok == len(uses) else "warn", "count": len(uses) - ok,
                "note": f"{ok} of {len(uses)} citations verified ({round(100 * ok / len(uses))}%)"}

    @reg.check("thesis_narrative", group="Thesis", label="Narrative across chapters",
               rule="Latest valid 'thesis-narrative-reviewer' review (reads every chapter against the plan)",
               pack="thesis-level", scope="thesis")
    def thesis_narrative(ctx):
        mine = [r for r in ctx.reviews if r["task"].get("role") == "thesis-narrative-reviewer"]
        if not mine:
            return {"state": "na", "note": "no review yet — create a 'thesis-narrative-reviewer' task"}
        latest = max(mine, key=lambda r: r["mtime"])
        f = latest["doc"].get("findings") or []
        sev = {x.get("severity") for x in f}
        return {"state": "bad" if "bad" in sev else "warn" if "warn" in sev else "ok",
                "items": [{"file": x.get("file", ""), "line": x.get("line", 0), "text": x.get("quote", "")[:260],
                           "detail": f"{x.get('severity')}: {x.get('problem', '')}"} for x in f],
                "note": f"{latest['task']['id']} by {(latest['doc'].get('agent') or {}).get('name', '?')}"}

    @reg.check("section_balance", group="Structure", label="Balance between sections",
               rule="No section above 1.8× or below 0.4× the chapter's average section length", pack="thesis-level")
    def section_balance(ctx, ch):
        secs = [s for s in ch.sections if s.words]
        if len(secs) < 3:
            return []
        avg = sum(s.words for s in secs) / len(secs)
        return [{"file": s.rel_path, "line": 0, "text": s.filename,
                 "detail": f"{s.words} words = {s.words / avg:.1f}× the average ({round(avg)})"}
                for s in secs if s.words > 1.8 * avg or s.words < 0.4 * avg]
