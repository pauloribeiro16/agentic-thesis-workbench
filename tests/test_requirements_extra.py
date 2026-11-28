"""Requirements not covered elsewhere (each test names its requirement)."""
import ast
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from atw import library, output
from atw.changes import ChangeService
from atw.citations import CitationIndex, CitationService, enrich_works
from atw.comments import CommentService
from atw.config import load_config
from atw.dialogue import DialogueService
from atw.pages import pdf_path
from atw.server import WorkbenchApp

ROOT = Path(__file__).resolve().parent.parent


def ws(toml: str, files: dict | None = None) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "thesis.toml").write_text(toml, encoding="utf-8")
    for rel, text in (files or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return d


BIB = "@article{Smith2020, author={Smith, Sam and Jones, J}, title={On Soil}, year={2020}}\n" \
      "@misc{GDPR, title={Regulation}, year={2016}}\n"


class Config(unittest.TestCase):
    def test_autodetect_without_thesis_toml(self):  # RF-CFG-01
        d = Path(tempfile.mkdtemp())
        (d / "refs.bib").write_text(BIB)
        (d / "chapters").mkdir()
        (d / "chapters" / "01_intro.md").write_text("# 1 Intro\n\nText.\n")
        cfg = load_config(d)
        self.assertEqual(cfg.bib_file, "refs.bib")
        from atw.formats import get_adapter
        self.assertEqual([c.number for c in get_adapter(cfg).discover_chapters()], [1])

    def test_minimal_thesis_loads_everywhere(self):  # RF-CFG-04
        d = ws('[project]\ntitle = "T"\n', {"chapters/01_a.md": "# 1 A\n\nText.\n"})
        app = WorkbenchApp(workspace=d)
        self.assertIn("config", app.state())


class Citations(unittest.TestCase):
    def index(self, syntax, extra=""):
        d = ws(f'[citations]\nbib_file = "refs.bib"\nsyntax = "{syntax}"\nno_year_keys = ["GDPR"]\n{extra}', {"refs.bib": BIB})
        return CitationIndex(CitationService(load_config(d)))

    def test_syntaxes_and_aliases(self):  # RF-CIT-02
        ay = self.index("author-year", '[citations.aliases]\n"smith, 2020b" = "Smith2020"\n')
        for c in ["Smith, 2020", "Smith et al., 2020", "Smith and Jones, 2020", "smith, 2020b", "GDPR", "Smith2020"]:
            self.assertIsNotNone(ay.resolve(c), c)
        self.assertIsNone(ay.resolve("Nobody, 2020"))
        for syntax, line in [("latex", r"As shown \citep{Smith2020}."), ("pandoc", "As shown [@Smith2020]."),
                             ("author-year", "As shown (Smith, 2020).")]:
            uses = self.index(syntax).uses_in("ch.md", line)
            self.assertEqual([u["key"] for u in uses], ["Smith2020"], syntax)

    def test_ledger_detects_an_altered_source(self):  # RF-CIT-03
        src = "The passage that supports the claim, exactly as archived."
        passage = "supports the claim"
        s = src.index(passage)
        d = ws('[citations]\nbib_file = "refs.bib"\nlibrary_dir = "lib"\nledger_file = "ledger.json"\n',
               {"refs.bib": BIB, "lib/Smith2020/full_text.md": src})
        row = {"key": "Smith2020", "source": "lit:Smith2020/full_text.md", "start": s, "end": s + len(passage),
               "sha256": hashlib.sha256(passage.encode()).hexdigest(), "verdict": "supports"}
        idx = CitationIndex(CitationService(load_config(d)))
        self.assertEqual(idx.passage_state(row), "ok")
        (d / "lib/Smith2020/full_text.md").write_text(src.replace("supports", "refutes"))
        self.assertEqual(CitationIndex(CitationService(load_config(d))).passage_state(row), "altered")

    def test_source_matches_entry_thresholds(self):  # RF-CIT-04
        d = ws('[citations]\nlibrary_dir = "lib"\n', {
            "lib/A/full_text.md": "Capacitive Soil Sensors Under Field Conditions",          # all title words
            "lib/B/full_text.md": "Capacitive Soil Sensors and nothing else",               # 3 of 6
            "lib/C/full_text.md": "Greenhouse climate control"})
        title = "Capacitive Soil Sensors Under Field Conditions"
        entries = [{"key": k, "title": title, "library_dir": f"lib/{k}"} for k in "ABC"] + [{"key": "D", "title": title}]
        enrich_works(load_config(d), entries)
        self.assertEqual([e["match"] for e in entries], ["confirmed", "doubtful", "mismatch", "no_source"])

    def test_integrity_manifest(self):  # RF-CIT-05
        d = ws('[citations]\nlibrary_dir = "lib"\nintegrity_manifest = "m.json"\n',
               {"lib/A/full_text.md": "x", "lib/B/full_text.md": "y"})
        sha = lambda p: hashlib.sha256((d / p).read_bytes()).hexdigest()
        (d / "m.json").write_text(json.dumps({"works": {"A": {"files": {"A/full_text.md": {"sha256": sha("lib/A/full_text.md")}}},
                                                        "B": {"files": {"B/full_text.md": {"sha256": "0" * 64}}}}}))
        entries = [{"key": k, "title": "t", "library_dir": f"lib/{k}"} for k in "ABC"]
        enrich_works(load_config(d), entries)
        self.assertEqual([e["seal"] for e in entries], ["intact", "changed", "not_sealed"])


class Pages(unittest.TestCase):
    def test_compile_runs_only_the_configured_command(self):  # RF-PG-02
        d = ws('[format]\nchapters_glob = "c/*.md"\ncompile_command = ["python3", "-c", '
               '"import sys; open(\'built-\' + sys.argv[1], \'w\').write(\'ok\')", "{chapter}"]\n', {"c/01_a.md": "# 1 A\n"})
        app = WorkbenchApp(workspace=d)
        self.assertTrue(app.compile(1)["ok"])
        for _ in range(100):
            if (d / "built-1").exists():
                break
            time.sleep(0.05)
        self.assertEqual((d / "built-1").read_text(), "ok")
        self.assertFalse(WorkbenchApp(workspace=ws('[project]\ntitle="x"\n')).compile(1)["ok"])

    def test_pdf_only_from_the_configured_path(self):  # RF-PG-03
        d = ws('[format.pages]\npdf = "b/ch{chapter}.pdf"\n', {"b/ch1.pdf": "%PDF", "other.pdf": "%PDF"})
        cfg = load_config(d)
        self.assertEqual(pdf_path(cfg, 1).resolve(), (d / "b/ch1.pdf").resolve())
        self.assertIsNone(pdf_path(cfg, 2))
        self.assertIsNone(pdf_path(load_config(ws('[project]\ntitle="x"\n')), 1))


TEXT = "# 1 A\n\nIntro sentence here. The quick brown fox jumps over the lazy dog. Closing sentence here.\n"
QUOTE = "The quick brown fox jumps over the lazy dog."


class CommentsAndChanges(unittest.TestCase):
    def setUp(self):
        self.d = ws('[format]\nchapters_glob = "c/*.md"\n[agents]\ncomments_dir = "cm"\nproposals_file = "p.json"\n'
                    'moderator_name = "Jane"\nsign_decisions = false\n', {"c/01_a.md": TEXT})
        self.cs = CommentService(load_config(self.d))

    def add(self):
        return self.cs.apply({"ch": 1, "action": "add", "file": "c/01_a.md", "quote": QUOTE, "kind": "fix", "text": "t"})[1]["comment"]["id"]

    def test_add_needs_text_in_the_chapter(self):  # RF-COM-01
        self.assertEqual(self.cs.apply({"ch": 1, "action": "add", "file": "c/01_a.md", "quote": "not there", "kind": "fix",
                                        "text": "t"})[0], 400)
        self.assertEqual(self.cs.apply({"ch": 1, "action": "add", "file": "../thesis.toml", "quote": "x", "kind": "fix",
                                        "text": "t"})[0], 400)

    def test_delete_only_own(self):  # RF-COM-09
        cid = self.add()
        data = self.cs.load(1)
        data["comments"][0]["author"] = "An agent"
        self.cs._save(1, data)
        self.assertEqual(self.cs.apply({"ch": 1, "action": "delete", "id": cid})[0], 403)
        cid2 = self.add()
        self.assertEqual(self.cs.apply({"ch": 1, "action": "delete", "id": cid2})[0], 200)

    def test_queue_lists_what_waits_for_the_author(self):  # RF-COM-10
        a, b = self.add(), self.add()
        self.cs.set_proposal(1, a, {"quote": QUOTE, "replacement": "A fox."}, "T-1", "agent")
        ids = [c["id"] for c in self.cs.queue()["items"]]
        self.assertEqual(ids, [a])

    def test_change_anchor_states(self):  # RF-CHG-08
        (self.d / "p.json").write_text(json.dumps({"version": 1, "topics": [], "items": [
            {"id": "P-1", "file": "c/01_a.md", "old": QUOTE, "new": "x", "status": "pending"},
            {"id": "P-2", "file": "c/01_a.md", "old": "absent text", "new": "x", "status": "pending"},
            {"id": "P-3", "file": "c/01_a.md", "old": "sentence here.", "new": "x", "status": "pending"}]}))
        states = [it["anchor"]["state"] for it in ChangeService(load_config(self.d)).load()["items"]]
        self.assertEqual(states, ["exact", "missing", "ambiguous"])


class Tasks(unittest.TestCase):
    def test_comment_answer_needs_a_chapter(self):  # RF-TSK-07
        from atw.tasks import TaskService
        d = ws('[format]\nchapters_glob = "c/*.md"\n', {"c/01_a.md": TEXT})
        ts = TaskService(load_config(d))
        t = ts.create(role="proposal-drafter")[0]
        (d / t["output"]).parent.mkdir(parents=True, exist_ok=True)
        (d / t["output"]).write_text(json.dumps({"task": t["id"], "kind": "proposals", "role": "proposal-drafter",
                                                 "agent": {"name": "A"}, "proposals": [
                                                     {"comment_id": "C-1", "file": "c/01_a.md", "quote": QUOTE,
                                                      "replacement": "x"}]}))
        ok, errs = ts.validate(t["id"])
        self.assertFalse(ok)
        self.assertTrue(any("no chapter" in e for e in errs), errs)


class Dialogue(unittest.TestCase):
    def setUp(self):
        self.d = ws('[agents]\ndialogue_dir = "dlg"\nmoderator_name = "Jane"\nsign_decisions = false\n',
                    {"dlg/T.md": "# T\n\n## Turn 1 — A (M) — 2026-01-01\n\n| Q1 | t | AGENT_CONSENSUS | Jane | x |\n"})
        self.svc = DialogueService(load_config(self.d))

    def test_append_only_with_conflict_detection(self):  # RF-GOV-06
        before = (self.d / "dlg/T.md").read_text()
        sha = self.svc.parse_thread(self.d / "dlg/T.md")["sha"]
        self.assertTrue(self.svc.append_decision("T.md", sha, [{"id": "Q1", "state": "APPROVED"}])[0])
        after = (self.d / "dlg/T.md").read_text()
        self.assertTrue(after.startswith(before.rstrip("\n")))
        ok, msg = self.svc.append_decision("T.md", sha, [{"id": "Q1", "state": "REJECTED"}])
        self.assertFalse(ok)
        self.assertIn("Conflict", msg)

    def test_threads_only_inside_the_dialogue_folder(self):  # RF-GOV-07
        (self.d / "outside.md").write_text("# x\n")
        for name in ["../outside.md", "/etc/hosts", "T.txt"]:
            self.assertFalse(self.svc.append_decision(name, "", [{"id": "Q1", "state": "APPROVED"}])[0], name)


class Template(unittest.TestCase):
    TPL = ROOT / "atw" / "templates" / "uminho-phd"

    def test_no_personal_or_thesis_data(self):  # RF-OUT-05
        latex = self.TPL / "latex"
        self.assertIn(r"\thethesisauthor", (latex / "covers" / "Covers.tex").read_text())
        self.assertIn(r"\thethesisauthor", (latex / "preamble" / "StatementofIntegrity.tex").read_text())
        main = (latex / "dissertation.tex").read_text()
        for macro in ("thesisauthor", "titleA", "titleB", "titleC", "phd", "supervisor"):
            self.assertRegex(main, rf"\\{macro}\{{\{{\{{[a-z_]+\}}\}}\}}", macro)
        self.assertEqual([p.name for p in latex.rglob("*") if p.suffix.lower() in (".ttf", ".otf")], [])
        self.assertEqual([p.name for p in latex.rglob("*.bib")], [])   # example bibliography ships as .bib.in
        acr = (latex / "preamble" / "Acronyms.tex").read_text()
        self.assertEqual(sum(1 for l in acr.splitlines() if l.startswith(r"\newacronym")), 1)

    @unittest.skipUnless(shutil.which("tectonic"), "tectonic not installed")
    def test_compiles(self):  # RF-OUT-06
        d = ws('[project]\ntitle = "A Test Thesis"\nauthor = "Test Author"\n[output]\ntemplate = "uminho-phd"\n')
        self.assertTrue(output.apply(load_config(d))[0])
        r = subprocess.run(["tectonic", "dissertation.tex"], cwd=d / "latex", capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertTrue((d / "latex" / "dissertation.pdf").is_file())


class LibraryRules(unittest.TestCase):
    def test_secrets_are_never_written(self):  # RF-LIB-07
        os.environ["ATW_TEST_ZKEY"] = "SECRET-TOKEN-123"
        d = ws('[citations]\nprovider = "zotero"\nbib_export = "out.bib"\n[citations.zotero]\nmode = "web"\n'
               'library_id = "42"\napi_key_env = "ATW_TEST_ZKEY"\n')
        seen = []

        def fake(url, headers):
            seen.append(headers)
            return 200, {"total-results": "1"}, json.dumps([{"title": "T", "author": [{"family": "X"}]}]).encode()
        library.sync(load_config(d), fetch=fake)
        self.assertEqual(seen[0]["Zotero-API-Key"], "SECRET-TOKEN-123")
        for p in d.rglob("*"):
            if p.is_file():
                self.assertNotIn("SECRET-TOKEN-123", p.read_text(errors="ignore"), p)

    def test_read_only(self):  # RF-LIB-08
        tree = ast.parse((ROOT / "atw" / "library.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "Request":
                self.assertFalse(any(k.arg in ("data", "method") for k in node.keywords), "library.py must only GET")


if __name__ == "__main__":
    unittest.main()
