"""Configurable structural, citation, and style consistency checks (read-only)."""
from __future__ import annotations

import json
import re
from typing import Any

from .citations import CitationService, extract_citations
from .config import WorkbenchConfig
from .formats import ChapterDoc, strip_citations

RE_MASK = re.compile(r"<!--.*?-->|```.*?```", re.S)
RE_HEAD = re.compile(r"^(#{1,6})\s+(.+)$")
RE_PLACEHOLDER = re.compile(r"\b(?:TODO|TBD|FIXME)\b|\?\?|\[\.\.\.\]")
RE_HTML = re.compile(r"<(?:mark|span|u|font)\b[^>]*>", re.I)
RE_FIRST_PERSON = re.compile(r"\b(?:we|our|ours|I|my|mine)\b")
RE_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
RE_CAPTION = re.compile(r"^\s*\*{0,2}(Table|Figure)\s+(\d+)\.(\d+)\s*[:.]")
RE_US_WORDS = re.compile(
    r"\b(?:model(?:ing|ed)|behavior\w*|organiz\w+|analyz\w+|artifacts?|defenses?|"
    r"catalog(?:s|ed|ing)?|centers?|favor\w*|colors?|recogniz\w+|summariz\w+|"
    r"prioritiz\w+|minimiz\w+|maximiz\w+|utiliz\w+|characteriz\w+|categoriz\w+|"
    r"formaliz\w+|standardiz\w+|optimiz\w+|authoriz\w+|emphasiz\w+|realiz\w+)\b",
    re.I,
)
RE_UK_WORDS = re.compile(
    r"\b(?:modelling|behaviour\w*|organis\w+|analys\w+|artefacts?|defences?|"
    r"catalogu\w+|centres?|favour\w*|colours?|recognis\w+|summaris\w+|"
    r"prioritis\w+|minimis\w+|maximis\w+|utilis\w+|characteris\w+|categoris\w+|"
    r"formalis\w+|standardis\w+|optimis\w+|authoris\w+|emphasis\w+|realis\w+)\b",
    re.I,
)


def _mask(raw: str) -> str:
    return RE_MASK.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), raw)


def _load_style_guide(cfg: WorkbenchConfig) -> list[dict[str, Any]]:
    p = cfg.workspace / cfg.style_guide_file
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("entries", []) if isinstance(data, dict) else []
    except Exception:
        return []


def run_quality_checks(
    cfg: WorkbenchConfig,
    chapters: list[ChapterDoc],
    cit_service: CitationService,
) -> dict[str, Any]:
    """Run all configured deterministic checks plus agent-review slots (narrative & tone)."""
    entries = cit_service.load_entries()
    bib_keys = {e["key"].lower() for e in entries}
    guide_entries = _load_style_guide(cfg)

    glossary_variants: list[tuple[str, str]] = []
    for ge in guide_entries:
        opts = ge.get("options") or {}
        for opt in opts.values():
            pref = opt.get("preferred")
            for var in opt.get("variants") or []:
                if pref and var and var != pref:
                    glossary_variants.append((var, pref))

    chapter_reports: list[dict[str, Any]] = []
    for ch in chapters:
        full_text = "\n\n".join(s.content for s in ch.sections)
        masked = _mask(full_text)
        lines = masked.splitlines()

        checks: list[dict[str, Any]] = []

        # 1. Word budget
        wc_state = "ok"
        if ch.words < ch.target_min:
            wc_state = "warn"
        elif ch.words > ch.target_max:
            wc_state = "bad"
        checks.append({
            "id": "word_budget",
            "group": "Limits",
            "label": "Word budget",
            "rule": f"Target {ch.target_min}–{ch.target_max} words",
            "state": wc_state,
            "count": ch.words,
            "items": [],
        })

        # 2. Section count (only if configured)
        if cfg.expected_sections is not None:
            sec_state = "ok" if len(ch.sections) == cfg.expected_sections else "warn"
            checks.append({
                "id": "sections",
                "group": "Structure",
                "label": "Section count",
                "rule": f"Expected {cfg.expected_sections} sections",
                "state": sec_state,
                "count": len(ch.sections),
                "items": [],
            })

        # 3. Placeholders
        ph_items = [
            {"line": i + 1, "text": l.strip()[:120]}
            for i, l in enumerate(lines)
            if RE_PLACEHOLDER.search(l)
        ]
        checks.append({
            "id": "placeholder",
            "group": "Structure",
            "label": "Unfinished placeholders",
            "rule": "No TODO/TBD/FIXME/?? in final text",
            "state": "bad" if ph_items else "ok",
            "count": len(ph_items),
            "items": ph_items[:30],
        })

        # 4. Stacked headings
        stacked: list[dict[str, Any]] = []
        prev_head = False
        for i, l in enumerate(lines):
            if not l.strip():
                continue
            is_h = bool(RE_HEAD.match(l.strip()))
            if is_h and prev_head:
                stacked.append({"line": i + 1, "text": l.strip()[:120]})
            prev_head = is_h
        checks.append({
            "id": "stacked",
            "group": "Structure",
            "label": "Stacked headings",
            "rule": "Introduce subsections before nesting headings",
            "state": "warn" if stacked else "ok",
            "count": len(stacked),
            "items": stacked[:30],
        })

        # 5. Long sentences
        long_items: list[dict[str, Any]] = []
        for i, l in enumerate(lines):
            s = l.strip()
            if not s or s.startswith("#") or s.startswith("|"):
                continue
            for sent in re.split(r"(?<=[.!?])\s+", strip_citations(s)):
                wcount = len(re.findall(r"[A-Za-z0-9À-ÿ]+", sent))
                if wcount > cfg.max_sentence_words:
                    long_items.append({"line": i + 1, "text": f"({wcount}w) {sent[:110]}..."})
        checks.append({
            "id": "long_sentences",
            "group": "Style",
            "label": f"Sentences over {cfg.max_sentence_words} words",
            "rule": f"Max {cfg.max_sentence_words} words per sentence (excluding citations)",
            "state": "warn" if long_items else "ok",
            "count": len(long_items),
            "items": long_items[:30],
        })

        # 6. First person (configurable)
        if cfg.forbid_first_person:
            fp_items = [
                {"line": i + 1, "text": l.strip()[:120]}
                for i, l in enumerate(lines)
                if l.strip() and not l.strip().startswith("#") and RE_FIRST_PERSON.search(l)
            ]
            checks.append({
                "id": "first_person",
                "group": "Style",
                "label": "First-person pronouns",
                "rule": "Configured to avoid first-person voice",
                "state": "bad" if fp_items else "ok",
                "count": len(fp_items),
                "items": fp_items[:30],
            })

        # 7. Spelling consistency (configurable)
        if cfg.spelling_variant in ("en-GB", "en-US"):
            rx = RE_US_WORDS if cfg.spelling_variant == "en-GB" else RE_UK_WORDS
            sp_items = [
                {"line": i + 1, "text": f"{m.group(0)} -> {l.strip()[:100]}"}
                for i, l in enumerate(lines)
                for m in [rx.search(l)]
                if m
            ]
            checks.append({
                "id": "spelling",
                "group": "Style",
                "label": f"Spelling consistency ({cfg.spelling_variant})",
                "rule": f"Enforce {cfg.spelling_variant} spelling",
                "state": "warn" if sp_items else "ok",
                "count": len(sp_items),
                "items": sp_items[:30],
            })

        # 8. Emphasis / cliché words
        if cfg.emphasis_words:
            emp_rx = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in cfg.emphasis_words) + r")\w*\b", re.I)
            emp_items = [
                {"line": i + 1, "text": f"{m.group(0)} — {l.strip()[:100]}"}
                for i, l in enumerate(lines)
                for m in [emp_rx.search(l)]
                if m
            ]
            checks.append({
                "id": "emphasis",
                "group": "Style",
                "label": "Emphasis / filler adjectives",
                "rule": "Review subjective emphasis words case by case",
                "state": "warn" if emp_items else "ok",
                "count": len(emp_items),
                "items": emp_items[:30],
            })

        # 9. Glossary consistency (from style/guide.json)
        if glossary_variants:
            gl_items: list[dict[str, Any]] = []
            for i, l in enumerate(lines):
                for var, pref in glossary_variants:
                    if re.search(rf"\b{re.escape(var)}\b", l):
                        gl_items.append({"line": i + 1, "text": f"'{var}' -> preferred '{pref}'"})
            checks.append({
                "id": "glossary",
                "group": "Consistency",
                "label": "Glossary terminology",
                "rule": "Follow approved terms in style/guide.json",
                "state": "warn" if gl_items else "ok",
                "count": len(gl_items),
                "items": gl_items[:30],
            })

        # 10. Formatting consistency (raw HTML & excessive bold)
        html_items = [
            {"line": i + 1, "text": l.strip()[:120]}
            for i, l in enumerate(lines)
            if RE_HTML.search(l)
        ]
        checks.append({
            "id": "html",
            "group": "Formatting",
            "label": "Inline HTML tags",
            "rule": "Keep manuscript free of raw <mark>/<span>/<u> tags",
            "state": "bad" if html_items else "ok",
            "count": len(html_items),
            "items": html_items[:30],
        })

        bold_items = [
            {"line": i + 1, "text": m.group(1)[:100]}
            for i, l in enumerate(lines)
            if not RE_CAPTION.match(l) and not l.strip().startswith("|")
            for m in RE_BOLD.finditer(l)
            if len(m.group(1).split()) > 6
        ]
        checks.append({
            "id": "bold",
            "group": "Formatting",
            "label": "Bold emphasis consistency",
            "rule": "Reserve bold for captions, defined terms, or short lead-ins",
            "state": "warn" if bold_items else "ok",
            "count": len(bold_items),
            "items": bold_items[:30],
        })

        # 11. Citations extracted
        cites = extract_citations(masked, syntax=cfg.citation_syntax)
        unresolved = [
            c for c in cites
            if cfg.citation_syntax in ("pandoc", "latex") and c.lower() not in bib_keys
        ]
        checks.append({
            "id": "citations",
            "group": "Citations",
            "label": "Unresolved citations",
            "rule": "Every citation key should map to an entry in the bibliography",
            "state": "warn" if unresolved else "ok",
            "count": len(unresolved),
            "items": [{"line": 0, "text": c} for c in unresolved[:30]],
        })

        # 12. Qualitative agent-review slots (Narrative & Tone)
        checks.append({
            "id": "narrative",
            "group": "Agent Review",
            "label": "Narrative coherence",
            "rule": "Qualitative review by an assigned agent",
            "state": "na",
            "count": 0,
            "items": [],
        })
        checks.append({
            "id": "tone",
            "group": "Agent Review",
            "label": "Writing tone & register",
            "rule": "Qualitative review by an assigned agent",
            "state": "na",
            "count": 0,
            "items": [],
        })

        chapter_reports.append({
            "chapter": ch.number,
            "title": ch.title,
            "words": ch.words,
            "checks": checks,
        })

    return {
        "style_guide_entries": len(guide_entries),
        "chapters": chapter_reports,
    }
