"""Page budget (the limit) and words (a reference), from the last compilation. A GET never compiles."""
from __future__ import annotations

from ..pages import pdf_page_count, thesis_budgets  # noqa: F401  (pdf_page_count re-exported for plugins/tests)

PLUGIN = {"id": "builtin.pages", "version": "2.0", "api_version": 1,
          "description": "Pages of the compiled chapter without the reference list, estimated without in-text "
                         "citations; words per page of the chapter turn the live word count into pages."}


def _budget(ctx, ch):
    if "_page_budget" not in ctx.__dict__:
        from ..formats import get_adapter
        ctx.__dict__["_page_budget"] = thesis_budgets(ctx.cfg, ctx.chapters, get_adapter(ctx.cfg))
    return ctx.__dict__["_page_budget"][ch.number]


def register(reg) -> None:
    @reg.check("pages", group="Limits", label="Pages", rule="Pages per chapter — the author's plan (without citations or references)",
               fail="bad")
    def pages(ctx, ch):
        b = _budget(ctx, ch)
        if not b["target"]:
            return {"state": "ok", "note": "no page limit configured"}
        lo, hi = b["target"]
        if not b["pdf_pages"]:
            return {"state": "na", "note": "compile the chapter to measure pages"}
        est = b["estimate_now"]
        state = "bad" if est > hi else "warn" if est < lo else "ok"
        note = (f"≈ {est:.1f} / {hi} without citations · PDF {b['pdf_pages']} pages with citations"
                + (" · text changed since the last compilation" if b["stale"] else ""))
        return {"state": state, "count": b["pdf_pages"], "note": note}

    @reg.check("word_budget", group="Limits", label="Words (reference)",
               rule="Words only translate the page limit; the chapter's own words per page come from its PDF")
    def word_budget(ctx, ch):
        b = _budget(ctx, ch)
        if b.get("words_fit"):
            state = "warn" if ch.words > b["words_fit"] else "ok"
            return {"state": state, "count": ch.words,
                    "note": f"≈ {int(b['words_fit'])} words fit in {b['target'][1]} pages ({b['words_per_page']} per page)"}
        if not ch.target_max:
            return {"state": "ok", "count": ch.words, "note": "not configured"}
        if ch.words < ch.target_min or ch.words > ch.target_max:
            return {"state": "warn", "count": ch.words, "note": f"reference {ch.target_min}–{ch.target_max}"}
        return {"state": "ok", "count": ch.words, "note": f"reference {ch.target_min}–{ch.target_max}"}
