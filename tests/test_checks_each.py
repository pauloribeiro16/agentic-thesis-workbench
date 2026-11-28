"""Every quality check, both ways: a text that breaks its rule must be reported (warn/bad) and a clean text must be
"ok". One test per check; the requirement id is RF-QL-<check id> (verify/requirements.toml)."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from atw.changes import ChangeService
from atw.comments import CommentService
from atw.config import load_config
from atw.dialogue import DialogueService
from atw.quality import run_quality_checks
from atw.tasks import TaskService

PARA = "This paragraph introduces the material of the section in plain words."
BASE_TOML = """
[project]
title = "T"
author = "A"
plan = ".thesis/plan.toml"
[format]
chapters_glob = "chapters/*/*.md"
[citations]
bib_file = "refs.bib"
library_dir = "sources"
syntax = "author-year"
ledger_file = ".thesis/citations/ledger.json"
[agents]
dialogue_dir = ".thesis/dialogue"
dialogue_profile = "en"
comments_dir = ".thesis/comments"
proposals_file = ".thesis/proposals/proposals.json"
moderator_name = "Jane"
sign_decisions = true
key_path = "{key}"
[quality]
packs = ["core", "citations", "style", "governance", "agent-review", "thesis-level"]
{quality}
"""
BIB = """@article{Alpha2019, author={Alpha, A}, title={One}, year={2019}}
@article{Zeta2020, author={Zeta, Z}, title={Two}, year={2020}}
@article{Smith2020, author={Smith, S}, title={Three}, year={2020}}
"""


def build(chapters: dict, quality: str = "", plan: str = "", files: dict | None = None, extra_toml: str = "") -> Path:
    """chapters: {1: {"01_a.md": text, ...}, 2: {...}}"""
    d = Path(tempfile.mkdtemp())
    key = d / "key"
    key.write_text("d" * 64)
    q = {"spelling_variant": '"none"', "forbid_first_person": "false"}
    for line in quality.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            q[k.strip()] = v.strip()
    qtext = "\n".join(f"{k} = {v}" for k, v in q.items())
    (d / "thesis.toml").write_text(BASE_TOML.format(key=key, quality=qtext) + extra_toml, encoding="utf-8")
    (d / ".thesis").mkdir()
    (d / ".thesis" / "plan.toml").write_text(plan, encoding="utf-8")
    (d / "refs.bib").write_text(BIB, encoding="utf-8")
    for n, sections in chapters.items():
        folder = d / "chapters" / f"{n:02d}_Chapter"
        folder.mkdir(parents=True)
        for name, text in sections.items():
            (folder / name).write_text(text, encoding="utf-8")
    for rel, text in (files or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return d


def state(ws: Path, check_id: str, chapter: int | None = 1) -> dict:
    res = run_quality_checks(load_config(ws))
    pool = res["thesis_checks"] if chapter is None else next(c for c in res["chapters"] if c["chapter"] == chapter)["checks"]
    found = [c for c in pool if c["id"] == check_id]
    if not found:
        raise AssertionError(f"check {check_id} did not run (chapter={chapter})")
    return found[0]


def sec(title: str, body: str = PARA) -> str:
    return f"## {title}\n\n{body}\n"


def one(text: str) -> dict:
    return {1: {"01_a.md": "# 1 Chapter\n\n" + PARA + "\n\n" + text}}


class Checks(unittest.TestCase):
    def both(self, check_id, bad_ws, good_ws, chapter=1):
        b, g = state(bad_ws, check_id, chapter), state(good_ws, check_id, chapter)
        self.assertIn(b["state"], ("warn", "bad"), f"{check_id} should report the violation: {b}")
        self.assertEqual(g["state"], "ok", f"{check_id} should accept the clean text: {g}")

    # --- structure -------------------------------------------------------------------------------
    def test_sections(self):
        plan = "[chapter_defaults]\nsections = 2\n"
        self.both("sections", build(one(sec("1.1 A")), plan=plan),
                  build({1: {"01_a.md": "# 1 C\n\n" + PARA, "02_b.md": sec("1.1 B")}}, plan=plan))

    def test_placeholder(self):
        self.both("placeholder", build(one(sec("1.1 A", "Finish this TODO later."))), build(one(sec("1.1 A"))))

    def test_stacked(self):
        self.both("stacked", build(one("## 1.1 A\n\n### 1.1.1 B\n\n" + PARA + "\n")), build(one(sec("1.1 A"))))

    def test_dangling(self):
        self.both("dangling", build(one(sec("1.1 A", "As Table 1.9 shows, it works."))),
                  build(one(sec("1.1 A", "As Table 1.1 shows, it works.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nTable 1.1: Numbers."))))

    def test_forward(self):
        chs = lambda ref: {1: {"01_a.md": "# 1 One\n\n" + PARA},
                           2: {"01_a.md": "# 2 Two\n\n" + PARA, "02_b.md": sec("2.1 Body", f"As {ref} explains, it holds."),
                               "03_c.md": sec("2.2 More")},
                           3: {"01_a.md": "# 3 Three\n\n" + PARA}}
        self.both("forward", build(chs("Chapter 3")), build(chs("Chapter 1")), chapter=2)

    def test_section_balance(self):
        long_text = " ".join([PARA] * 30)
        self.both("section_balance",
                  build({1: {"01_a.md": "# 1 C\n\n" + PARA, "02_b.md": sec("1.1 B"), "03_c.md": sec("1.2 C", long_text)}}),
                  build({1: {"01_a.md": "# 1 C\n\n" + PARA, "02_b.md": sec("1.1 B"), "03_c.md": sec("1.2 C")}}))

    def test_generated_sync(self):
        toml = '[format.sync]\ncommand = ["python3", "-c", "print(\'generated\')"]\ntarget = "out/ch{chapter}.tex"\n'
        self.both("generated_sync", build(one(sec("1.1 A")), files={"out/ch1.tex": "stale\n"}, extra_toml=toml),
                  build(one(sec("1.1 A")), files={"out/ch1.tex": "generated\n"}, extra_toml=toml))

    # --- formatting ------------------------------------------------------------------------------
    def test_table_caption(self):
        table = "Table 1.1 lists them.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        self.both("table_caption", build(one(sec("1.1 A", table))),
                  build(one(sec("1.1 A", table + "\nTable 1.1: Numbers."))))

    def test_figure_caption(self):
        fig = "Figure 1.1 shows it.\n\n![diagram](d.png)\n"
        self.both("figure_caption", build(one(sec("1.1 A", fig))),
                  build(one(sec("1.1 A", fig + "\nFigure 1.1: A diagram."))))

    def test_numbering(self):
        t = lambda n: f"Table {n} lists them.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nTable {n}: Numbers."
        self.both("numbering", build(one(sec("1.1 A", t("1.2")))), build(one(sec("1.1 A", t("1.1")))))

    def test_float_ref(self):
        tbl = "| a | b |\n|---|---|\n| 1 | 2 |\n\nTable 1.1: Numbers."
        self.both("float_ref", build(one(sec("1.1 A", tbl))), build(one(sec("1.1 A", "Table 1.1 lists them.\n\n" + tbl))))

    def test_html(self):
        self.both("html", build(one(sec("1.1 A", "A <mark>marked</mark> word."))), build(one(sec("1.1 A"))))

    def test_bold(self):
        self.both("bold", build(one(sec("1.1 A", "The **sensor** is cheap. Later the **sensor** fails."))),
                  build(one(sec("1.1 A", "The **sensor** is cheap. Later the sensor fails."))))

    # --- writing ---------------------------------------------------------------------------------
    def test_long(self):
        q = "max_sentence_words = 14"
        self.both("long", build(one(sec("1.1 A", "This sentence has far more than fourteen words in it, which clearly breaks the limit that the author set.")), q),
                  build(one(sec("1.1 A", "This sentence is short.")), q))

    def test_first_person(self):
        q = "forbid_first_person = true"
        self.both("first_person", build(one(sec("1.1 A", "We show that it works.")), q),
                  build(one(sec("1.1 A", "This shows that it works.")), q))

    def test_spelling(self):
        q = 'spelling_variant = "en-GB"'
        self.both("spelling", build(one(sec("1.1 A", "The color of the soil.")), q),
                  build(one(sec("1.1 A", "The colour of the soil.")), q))

    def test_heading_spelling(self):
        q = 'spelling_variant = "en-GB"'
        self.both("heading_spelling", build(one(sec("1.1 Soil color")), q), build(one(sec("1.1 Soil colour")), q))

    def test_prohibited(self):
        q = 'prohibited_phrases = ["significant gap"]'
        self.both("prohibited", build(one(sec("1.1 A", "There is a significant gap here.")), q),
                  build(one(sec("1.1 A", "There is a gap here.")), q))

    def test_emphasis(self):
        q = 'emphasis_words = ["crucial"]'
        self.both("emphasis", build(one(sec("1.1 A", "This is crucial.")), q), build(one(sec("1.1 A", "This matters.")), q))

    def test_terms(self):
        guide = json.dumps({"version": 1, "entries": [{"thread": "STYLE.md", "q": "Q1", "kind": "Term", "title": "Life-cycle",
                                                        "options": {"Option A": {"preferred": "life-cycle", "variants": ["lifecycle"]}}}]})
        toml = '[agents.extra]\n'

        def ws(word):
            d = build(one(sec("1.1 A", f"The {word} of a sensor.")), files={
                ".thesis/style/guide.json": guide,
                ".thesis/dialogue/STYLE.md": "# STYLE\n\n## Turn 1 — Agent (M) — 2026-01-01\n\n| Q1 | Life-cycle | AGENT_CONSENSUS | Jane | A |\n"})
            dlg = DialogueService(load_config(d))
            sha = dlg.parse_thread(d / ".thesis/dialogue/STYLE.md")["sha"]
            ok, msg = dlg.append_decision("STYLE.md", sha, [{"id": "Q1", "state": "APPROVED", "note": "Chosen option: Option A"}])
            assert ok, msg
            return d
        self.both("terms", ws("lifecycle"), ws("life-cycle"))

    # --- citations -------------------------------------------------------------------------------
    def test_cite_unresolved(self):
        self.both("cite_unresolved", build(one(sec("1.1 A", "It holds (Nobody, 2001)."))),
                  build(one(sec("1.1 A", "It holds (Smith, 2020)."))))

    SOURCE = "Smith shows that it holds in every case we tried."

    def _ledger(self, verdict):
        import hashlib
        passage = "it holds in every case"
        start = self.SOURCE.index(passage)
        return json.dumps({"version": 1, "entries": [{"key": "Smith2020", "file": "chapters/01_Chapter/01_a.md",
                                                      "claim": "It holds", "verdict": verdict,
                                                      "source": "lit:Smith2020/full_text.md", "start": start,
                                                      "end": start + len(passage),
                                                      "sha256": hashlib.sha256(passage.encode()).hexdigest()}]})

    def _cite_files(self, verdict):
        return {".thesis/citations/ledger.json": self._ledger(verdict), "sources/Smith2020/full_text.md": self.SOURCE}

    def test_cite_verified(self):
        self.both("cite_verified",
                  build(one(sec("1.1 A", "It holds (Smith, 2020). Also (Alpha, 2019).")),
                        files=self._cite_files("supports")),
                  build(one(sec("1.1 A", "It holds (Smith, 2020).")), files=self._cite_files("supports")))

    def test_cite_problem(self):
        self.both("cite_problem",
                  build(one(sec("1.1 A", "It holds (Smith, 2020).")), files=self._cite_files("partial")),
                  build(one(sec("1.1 A", "It holds (Smith, 2020).")), files=self._cite_files("supports")))

    def test_cite_order(self):
        self.both("cite_order", build(one(sec("1.1 A", "Both agree (Zeta, 2020; Alpha, 2019)."))),
                  build(one(sec("1.1 A", "Both agree (Alpha, 2019; Zeta, 2020)."))))

    # --- limits ----------------------------------------------------------------------------------
    def test_word_budget(self):
        plan = "[chapter_defaults]\nwords = [5, 40]\n"
        self.both("word_budget", build(one(sec("1.1 A", " ".join([PARA] * 10))), plan=plan),
                  build(one(sec("1.1 A")), plan=plan))

    def test_pages(self):
        toml = '[format.pages]\npdf = "pdf/ch{chapter}.pdf"\n'
        plan = "[chapter_defaults]\npages = [1, 2]\n"
        fake_pdf = lambda n: f"%PDF-1.4\n1 0 obj << /Type /Pages /Count {n} >> endobj\n%%EOF\n"
        self.both("pages", build(one(sec("1.1 A")), plan=plan, extra_toml=toml, files={"pdf/ch1.pdf": fake_pdf(5)}),
                  build(one(sec("1.1 A")), plan=plan, extra_toml=toml, files={"pdf/ch1.pdf": fake_pdf(2)}))

    # --- agent reviews -------------------------------------------------------------------------------
    def _review(self, role, findings, chapter=1, check=None):
        d = build({1: {"01_a.md": "# 1 One\n\n" + PARA}, 2: {"01_a.md": "# 2 Two\n\nAs Chapter 1 said. " + PARA}})
        ts = TaskService(load_config(d))
        task = ts.create(role=role, chapter=chapter if role != "thesis-narrative-reviewer" else None)[0]
        out = d / task["output"]
        out.parent.mkdir(parents=True, exist_ok=True)
        files = task.get("files") or ["chapters/01_Chapter/01_a.md"]
        out.write_text(json.dumps({"task": task["id"], "kind": "review", "role": role, "agent": {"name": "A"},
                                   "independent": True, "summary": "s",
                                   "findings": [{"file": files[0], "line": 1, "quote": "x", "severity": "warn",
                                                 "category": "c", "problem": "p", "suggestion": "s"}] if findings else []}))
        ok, errs = ts.validate(task["id"])
        assert ok, errs
        return d

    def test_tone(self):
        self.both("tone", self._review("tone-reviewer", True), self._review("tone-reviewer", False))

    def test_narrative(self):
        self.both("narrative", self._review("narrative-reviewer", True), self._review("narrative-reviewer", False))

    def test_consistency(self):
        self.both("consistency", self._review("consistency-checker", True), self._review("consistency-checker", False))

    def test_thesis_narrative(self):
        self.both("thesis_narrative", self._review("thesis-narrative-reviewer", True),
                  self._review("thesis-narrative-reviewer", False), chapter=None)

    # --- thesis level ----------------------------------------------------------------------------
    def test_plan_structure(self):
        plan = lambda n: "".join(f"[[chapters]]\nnumber = {i}\ntitle = \"C{i}\"\n" for i in range(1, n + 1))
        self.both("plan_structure", build(one(sec("1.1 A")), plan=plan(2)), build(one(sec("1.1 A")), plan=plan(1)), chapter=None)

    def test_page_balance(self):
        toml = '[format.pages]\npdf = "pdf/ch{chapter}.pdf"\n'
        plan = "[chapter_defaults]\npages = [1, 2]\n"
        fake_pdf = lambda n: f"%PDF-1.4\n1 0 obj << /Type /Pages /Count {n} >> endobj\n%%EOF\n"
        self.both("page_balance", build(one(sec("1.1 A")), plan=plan, extra_toml=toml, files={"pdf/ch1.pdf": fake_pdf(5)}),
                  build(one(sec("1.1 A")), plan=plan, extra_toml=toml, files={"pdf/ch1.pdf": fake_pdf(2)}), chapter=None)

    def test_chapter_links(self):
        body = " ".join([PARA] * 40)
        chs = lambda t: {1: {"01_a.md": "# 1 One\n\n" + PARA}, 2: {"01_a.md": "# 2 Two\n\n" + t + " " + body}}
        self.both("chapter_links", build(chs("Nothing here.")), build(chs("As Chapter 1 said.")), chapter=None)

    def test_term_variants(self):
        chs = lambda w: {1: {"01_a.md": "# 1 One\n\nThe lifecycle of a sensor."}, 2: {"01_a.md": f"# 2 Two\n\nAs Chapter 1 said, the {w} of a sensor."}}
        self.both("term_variants", build(chs("life-cycle")), build(chs("lifecycle")), chapter=None)

    def test_citations_overall(self):
        self.both("citations_overall",
                  build(one(sec("1.1 A", "It holds (Smith, 2020). Also (Alpha, 2019).")),
                        files=self._cite_files("supports")),
                  build(one(sec("1.1 A", "It holds (Smith, 2020).")), files=self._cite_files("supports")),
                  chapter=None)

    # --- governance ------------------------------------------------------------------------------
    def _props(self, item):
        return {".thesis/proposals/proposals.json": json.dumps({"version": 1, "topics": [], "items": [item] if item else []})}

    def test_changes_pending(self):
        it = {"id": "P-1", "file": "chapters/01_Chapter/01_a.md", "old": PARA, "new": "x", "status": "pending"}
        self.both("changes_pending", build(one(sec("1.1 A")), files=self._props(it)), build(one(sec("1.1 A")), files=self._props(None)), None)

    def test_changes_lost(self):
        lost = {"id": "P-1", "file": "chapters/01_Chapter/01_a.md", "old": "text not in the file", "new": "x", "status": "pending"}
        here = dict(lost, old=PARA)
        self.both("changes_lost", build(one(sec("1.1 A")), files=self._props(lost)), build(one(sec("1.1 A")), files=self._props(here)), None)

    def test_changes_register(self):
        it = {"id": "P-1", "file": "chapters/01_Chapter/01_a.md", "old": PARA, "new": "x", "status": "rejected"}
        self.both("changes_register", build(one(sec("1.1 A")), files=self._props(it)),
                  build(one(sec("1.1 A")), files=self._props(dict(it, registered="2026-01-01"))), None)

    def test_changes_review(self):
        it = {"id": "P-1", "file": "chapters/01_Chapter/01_a.md", "old": PARA, "new": "x", "status": "applied"}
        self.both("changes_review", build(one(sec("1.1 A")), files=self._props(it)),
                  build(one(sec("1.1 A")), files=self._props(dict(it, decision="kept"))), None)

    def _comment(self, status, quote=PARA):
        d = build(one(sec("1.1 A")))
        cs = CommentService(load_config(d))
        _, out = cs.apply({"ch": 1, "action": "add", "file": "chapters/01_Chapter/01_a.md", "quote": PARA, "kind": "fix", "text": "t"})
        data = cs.load(1)
        data["comments"][0]["status"] = status
        data["comments"][0]["quote"] = quote
        data["comments"][0]["prefix"] = data["comments"][0]["suffix"] = ""
        cs._save(1, data)
        return d

    def test_comments_to_close(self):
        self.both("comments_to_close", self._comment("addressed"), self._comment("open"), None)

    def test_comments_orphan(self):
        self.both("comments_orphan", self._comment("open", "zzz completely unrelated words that are nowhere qqq"),
                  self._comment("open"), None)

    def _thread(self, rows):
        return {".thesis/dialogue/CH1.md": "# CH1\n\n## Turn 1 — Agent (M) — 2026-01-01\n\n" + rows}

    def test_dec_pending(self):
        self.both("dec_pending", build(one(sec("1.1 A")), files=self._thread("| Q1 | T | AGENT_CONSENSUS | Jane | x |\n")),
                  build(one(sec("1.1 A")), files=self._thread("| Q1 | T | OPEN | Jane | x |\n")), None)

    def test_dec_unauthorised(self):
        self.both("dec_unauthorised", build(one(sec("1.1 A")), files=self._thread("| Q1 | T | APPROVED | Jane | x |\n")),
                  build(one(sec("1.1 A")), files=self._thread("| Q1 | T | OPEN | Jane | x |\n")), None)

    def test_tasks_invalid(self):
        def ws(valid):
            d = build(one(sec("1.1 A")))
            ts = TaskService(load_config(d))
            t = ts.create(role="tone-reviewer", chapter=1)[0]
            (d / t["output"]).parent.mkdir(parents=True, exist_ok=True)
            (d / t["output"]).write_text(json.dumps({"task": t["id"], "kind": "review", "role": "tone-reviewer",
                                                     "agent": {"name": "A"}, "independent": valid, "summary": "s"}))
            ts.validate(t["id"])
            return d
        self.both("tasks_invalid", ws(False), ws(True), None)


class CatalogueIsCovered(unittest.TestCase):
    """RF-QL-00: every registered check has a test above (so a new check cannot ship untested)."""

    def test_every_check_has_a_test(self):
        from atw.plugins import load_registry
        ids = set(load_registry(load_config(build(one(sec("1.1 A"))))).checks)
        tested = {n[len("test_"):] for n in dir(Checks) if n.startswith("test_")}
        self.assertEqual(sorted(ids - tested), [], "checks without a test")


if __name__ == "__main__":
    unittest.main()
