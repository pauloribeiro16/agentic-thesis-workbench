"""Writing-style checks configured from [quality] in thesis.toml and the style guide."""
from __future__ import annotations

import re

from ..formats import strip_citations

PLUGIN = {"id": "builtin.style", "version": "1.0", "api_version": 1,
          "description": "Sentence length, person, spelling variant, prohibited phrases, emphasis, glossary."}

US = (r"model(?:ing|ed|er|ers)|behavior\w*|organiz\w+|analyz\w+|artifacts?|defenses?|label(?:ed|ing)|catalog(?:s|ed|ing)?|"
      r"centers?|favor\w*|colors?|recogniz\w+|summariz\w+|prioritiz\w+|minimiz\w+|maximiz\w+|utiliz\w+|characteriz\w+|"
      r"categoriz\w+|formaliz\w+|standardiz\w+|optimiz\w+|authoriz\w+|emphasiz\w+|realiz\w+|operationaliz\w+|"
      r"specializ\w+|generaliz\w+|normaliz\w+|customiz\w+|finaliz\w+")
UK = (r"modelling|modelled|behaviour\w*|organis\w+|analys(?:e|ed|es|ing)|artefacts?|defences?|labell(?:ed|ing)|"
      r"catalogu(?:e|es|ed|ing)|centres?|favour\w*|colours?|recognis\w+|summaris\w+|prioritis\w+|minimis\w+|"
      r"maximis\w+|utilis\w+|characteris\w+|categoris\w+|formalis\w+|standardis\w+|optimis\w+|authoris\w+|"
      r"emphasis(?:e|ed|es|ing)|realis(?:e|ed|es|ing)")
RE_FIRST = re.compile(r"\b(?:we|our|ours|us|I|my|mine)\b")
RE_SENT = re.compile(r"[^.!?]+(?:[.!?]+|$)")
RE_QUOTED = re.compile(r"\"[^\"\n]*\"|“[^”\n]*”|«[^»\n]*»")


def _wording(line: str) -> str:
    """Text the author wrote: no citations, no quotations, no inline code."""
    return RE_QUOTED.sub(" ", re.sub(r"`[^`]*`", " ", strip_citations(line)))


def _fold_opt(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", s.strip().lower()) if not unicodedata.combining(c))


def _words(s: str) -> int:
    return len(re.findall(r"[0-9A-Za-zÀ-ÿ][0-9A-Za-zÀ-ÿ'’\-]*", s))


def register(reg) -> None:
    @reg.check("long", group="Writing", label="Long sentences",
               rule="Sentences above [quality] max_sentence_words (citations excluded)", pack="style")
    def long(ctx, ch):
        lim, out = ctx.cfg.max_sentence_words, []
        if not lim:
            return {"state": "ok", "note": "not configured"}
        for s in ctx.sections[ch.number]:
            for no, line in s.rows("prose", "list"):
                for sent in RE_SENT.findall(strip_citations(line)):
                    n = _words(re.sub(r"[*_`]", "", sent))
                    if n > lim:
                        out.append(s.item(no, f"{n} words"))
        return out

    @reg.check("first_person", group="Writing", label="First person",
               rule="[quality] forbid_first_person = true", pack="style", fail="bad")
    def first_person(ctx, ch):
        if not ctx.cfg.forbid_first_person:
            return {"state": "ok", "note": "allowed"}
        return [s.item(no, m.group(0)) for s in ctx.sections[ch.number]
                for no, l in s.rows("prose", "list") for m in RE_FIRST.finditer(_wording(l))]

    def _variant_rx(ctx):
        v = ctx.cfg.spelling_variant
        return re.compile(rf"\b(?:{US if v == 'en-GB' else UK})\b", re.I) if v in ("en-GB", "en-US") else None

    @reg.check("spelling", group="Writing", label="Spelling variant in the text",
               rule="[quality] spelling_variant (en-GB / en-US)", pack="style")
    def spelling(ctx, ch):
        rx = _variant_rx(ctx)
        if rx is None:
            return {"state": "ok", "note": "not configured"}
        out = []
        for s in ctx.sections[ch.number]:
            for no, line in s.rows("prose", "list", "table", "caption"):
                said = _wording(line)
                for m in rx.finditer(said):
                    before = said[:m.start()].rstrip()
                    if m.group(0)[0].isupper() and before and before[-1] not in ".:|!?-•":
                        continue  # proper noun, e.g. "World Health Organization"
                    out.append(s.item(no, m.group(0)))
        return out

    @reg.check("heading_spelling", group="Writing", label="Spelling variant in headings",
               rule="Headings follow the spelling variant (changing a heading needs the author's approval)", pack="style")
    def heading_spelling(ctx, ch):
        rx = _variant_rx(ctx)
        if rx is None:
            return {"state": "ok", "note": "not configured"}
        return [s.item(no, m.group(0)) for s in ctx.sections[ch.number] for no, l in s.rows("heading") for m in rx.finditer(l)]

    @reg.check("prohibited", group="Writing", label="Prohibited expressions",
               rule="[quality] prohibited_phrases", pack="style", fail="bad")
    def prohibited(ctx, ch):
        phrases = [p for p in ctx.cfg.prohibited_phrases if p]
        return [s.item(no, p) for s in ctx.sections[ch.number] for no, l in s.rows("prose", "list", "table", "caption", "heading")
                for p in phrases if p.lower() in l.lower()]

    @reg.check("emphasis", group="Writing", label="Emphasis words",
               rule="[quality] emphasis_words — read case by case", pack="style")
    def emphasis(ctx, ch):
        if not ctx.cfg.emphasis_words:
            return []
        rx = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in ctx.cfg.emphasis_words) + r")\w*\b", re.I)
        return [s.item(no, m.group(0)) for s in ctx.sections[ch.number]
                for no, l in s.rows("prose", "list") for m in rx.finditer(_wording(l))]

    @reg.check("terms", group="Writing", label="Terms outside the glossary",
               rule="Only terms the author approved in the style guide count", pack="style")
    def terms(ctx, ch):
        pairs = []
        by_q = {(q["thread"], q["id"]): q for q in ctx.questions}
        for ge in ctx.style_guide:
            opts = ge.get("options") or {}
            q = by_q.get((ge.get("thread"), ge.get("q")))
            if not opts or not q or q["state"] != "APPROVED" or not q.get("authenticated"):
                continue  # only terms the author approved with a sealed decision
            m = re.search(r"(?:Chosen option|Op[çc][ãa]o escolhida):\s*([^.;)]+)", q.get("decision_note", ""), re.I)
            want = _fold_opt(m.group(1)) if m else None
            chosen = next((v for k, v in opts.items() if _fold_opt(k) == want), None) or next(iter(opts.values()))
            pref = (chosen or {}).get("preferred")
            for var in (chosen or {}).get("variants") or []:
                if pref and var and var != pref:
                    pairs.append((re.compile(rf"\b{re.escape(var)}\b"), var, pref))
        return [s.item(no, f"'{var}' → '{pref}'") for s in ctx.sections[ch.number]
                for no, l in s.rows("prose", "list", "table", "caption") for rx, var, pref in pairs if rx.search(_wording(l))]
