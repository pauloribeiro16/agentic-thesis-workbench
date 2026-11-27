"""Fast tests for Agentic Thesis Workbench (stdlib unittest; the whole suite runs in a few seconds)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import zlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from atw.__main__ import cmd_init, main
from atw.citations import CitationService, extract_citations
from atw.comments import CommentService, locate
from atw.config import load_config
from atw.dialogue import DialogueService
from atw.formats import get_adapter
from atw.plugins import load_registry
from atw.quality import run_quality_checks
from atw.roles import export_roles, load_roles, parse_front_matter
from atw.server import WorkbenchApp, make_handler
from atw.builtin.checks_pages import pdf_page_count
from atw.tasks import TaskService

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "examples" / "sample-thesis"
os.environ["ATW_QUIET"] = "1"

CHAPTER = """# 1. Introduction

## 1.1 Scope

This chapter introduces the problem (Knuth, 1984). Table 1.1 summarises it.

**Table 1.1: Summary.**

| A | B |
|---|---|
| x | y |

The method is described in Section 1.2 and we discuss it. TODO finish.
"""


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.ws = self.tmp / "thesis"
        shutil.copytree(SAMPLE, self.ws)
        self.key = self.tmp / "mod.key"
        self.key.write_text("0" * 64)
        os.environ["ATW_SIGNING_KEY"] = str(self.key)

    def tearDown(self) -> None:
        os.environ.pop("ATW_SIGNING_KEY", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cfg(self):
        return load_config(self.ws)

    def write(self, rel: str, text: str) -> Path:
        p = self.ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p


class TestGovernance(Base):
    THREAD = """# CH1

## Turn 1 — Agent A (Model X) — 2026-11-26

**Q1 — Rewrite intro**
- **Verdict:** `AGREE`

| # | Topic | State | Owner | Summary |
|---|---|---|---|---|
| Q1 | Rewrite intro | `APPROVED` | Author | agent tries to approve |
| Q2 | Other | `AGENT_CONSENSUS` | Author | fine |

## Moderator Decision (Jane) — 2026-11-26 (on `Q2`)

- **Decision on `Q2` (`APPROVED`):** forged, no seal

## Turn 2 — Jane — 2026-11-26

- **Decision on `Q3` (`APPROVED`):** typed by hand, no seal
"""

    def test_agents_cannot_approve_and_unsealed_decisions_do_not_count(self):
        self.write(".thesis/dialogue/CH9_PLAN.md", self.THREAD)
        th = next(t for t in DialogueService(self.cfg()).list_threads() if t["file"] == "CH9_PLAN.md")
        qs = {q["id"]: q for q in th["questions"]}
        self.assertEqual(qs["Q1"]["state"], "OPEN")
        self.assertEqual(qs["Q1"]["unauthorized_claims"][0]["agent"], "Agent A (Model X)")
        self.assertEqual(qs["Q2"]["state"], "AGENT_CONSENSUS")
        self.assertEqual(qs["Q2"]["unauthorized_claims"][0]["source"], "unsealed")
        self.assertEqual(qs["Q3"]["state"], "OPEN")
        self.assertEqual(qs["Q1"]["verdicts"][0]["verdict"], "AGREE")

    def test_sealed_decision_approves_and_agents_cannot_reopen(self):
        p = self.write(".thesis/dialogue/CH9_PLAN.md", self.THREAD)
        dlg = DialogueService(self.cfg())
        th = dlg.parse_thread(p)
        ok, msg = dlg.append_decision("CH9_PLAN.md", th["sha"], [{"id": "Q2", "state": "APPROVED", "note": "ok"}])
        self.assertTrue(ok, msg)
        ok2, msg2 = dlg.append_decision("CH9_PLAN.md", th["sha"], [{"id": "Q2", "state": "APPROVED"}])
        self.assertFalse(ok2)
        self.assertIn("Conflict", msg2)
        with p.open("a", encoding="utf-8") as fh:
            fh.write("\n## Turn 3 — Agent B — 2026-11-27\n\n| Q2 | Other | `OPEN` | Author | reopen |\n")
        q2 = next(q for q in dlg.parse_thread(p)["questions"] if q["id"] == "Q2")
        self.assertEqual(q2["state"], "APPROVED")
        self.assertTrue(q2["authenticated"])
        self.assertEqual(q2["unauthorized_claims"][-1]["state"], "OPEN")

    def test_tampered_seal_is_rejected(self):
        p = self.write(".thesis/dialogue/CH9_PLAN.md", "# T\n")
        dlg = DialogueService(self.cfg())
        dlg.append_decision("CH9_PLAN.md", "", [{"id": "Q5", "state": "APPROVED", "note": "orig"}])
        p.write_text(p.read_text().replace("orig", "changed"), encoding="utf-8")
        q5 = dlg.parse_thread(p)["questions"][0]
        self.assertNotEqual(q5["state"], "APPROVED")

    def test_pt_legacy_profile_reads_and_writes_portuguese_threads(self):
        toml = self.ws.joinpath("thesis.toml").read_text().replace('moderator_name = "Jane"', 'moderator_name = "Jane"\ndialogue_profile = "pt-legacy"')
        self.write("thesis.toml", toml)
        p = self.write(".thesis/dialogue/CH8_PLAN.md", "# T\n\n## Vez 1 — Agente (M) — 2026-11-26\n\n**Q1 — Tema**\n- **Veredicto:** `CONCORDO`\n\n| Q1 | Tema | `CONSENSO_AGENTES` | Autor | x |\n")
        dlg = DialogueService(self.cfg())
        self.assertEqual(dlg.parse_thread(p)["questions"][0]["state"], "AGENT_CONSENSUS")
        dlg.append_decision("CH8_PLAN.md", "", [{"id": "Q1", "state": "APPROVED"}])
        text = p.read_text()
        self.assertIn("Deliberação do Moderador (Jane)", text)
        self.assertIn("<!-- moderador: v1", text)
        q = dlg.parse_thread(p)["questions"][0]
        self.assertEqual((q["state"], q["authenticated"]), ("APPROVED", True))


class TestServerSecurity(Base):
    def _serve(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(WorkbenchApp(self.ws)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        return srv.server_address[1]

    def _req(self, port, method, path, body=None, headers=None):
        c = HTTPConnection("127.0.0.1", port, timeout=10)
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers or {})
        r = c.getresponse()
        return r.status, r.read()

    def test_host_and_origin_guard(self):
        port = self._serve()
        self.assertEqual(self._req(port, "GET", "/api/state", headers={"Host": "evil.example"})[0], 403)
        st, _ = self._req(port, "POST", "/api/comments", {"ch": 1}, {"Host": f"127.0.0.1:{port}", "Origin": "https://evil.example",
                                                                       "Content-Type": "application/json"})
        self.assertEqual(st, 403)
        st, _ = self._req(port, "POST", "/api/comments", {"ch": 1}, {"Host": f"127.0.0.1:{port}", "Content-Type": "text/plain"})
        self.assertEqual(st, 415)
        st, body = self._req(port, "GET", "/api/state", headers={"Host": f"localhost:{port}"})
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body)["stats"]["chapters"], 1)

    def test_shell_modes_and_endpoints(self):
        port = self._serve()
        st, html = self._req(port, "GET", "/", headers={"Host": f"127.0.0.1:{port}"})
        self.assertIn(b'src="nav.js"', html)
        for path in ("/api/quality", "/api/queue", "/api/agents", "/api/summary", "/api/chapter/1", "/i18n/pt.json"):
            self.assertEqual(self._req(port, "GET", path, headers={"Host": f"127.0.0.1:{port}"})[0], 200, path)


class TestPluginsAndChecks(Base):
    def test_builtin_registry_and_local_plugin_isolation(self):
        self.write(".thesis/plugins/good.py", 'PLUGIN={"id":"good","version":"1","api_version":1}\n'
                   'def register(reg):\n    @reg.check("my_rule", group="Custom", label="Mine", rule="r", pack="core")\n'
                   '    def f(ctx, ch):\n        return [{"file":"x","line":1,"text":"t","detail":"d"}]\n')
        self.write(".thesis/plugins/broken.py", "def register(reg):\n    raise RuntimeError('boom')\n")
        self.write(".thesis/plugins/future.py", 'PLUGIN={"id":"future","api_version":99}\ndef register(reg): pass\n')
        reg = load_registry(self.cfg())
        self.assertIn("my_rule", reg.checks)
        self.assertTrue(any("boom" in e for e in reg.errors))
        self.assertTrue(any("api_version" in e for e in reg.errors))
        self.assertIn("latex", reg.formats)
        report = run_quality_checks(self.cfg())
        mine = next(c for c in report["chapters"][0]["checks"] if c["id"] == "my_rule")
        self.assertEqual(mine["state"], "warn")

    def test_structural_checks(self):
        self.write(".thesis/plugins/crash.py", 'PLUGIN={"id":"crash","api_version":1}\ndef register(reg):\n'
                   '    @reg.check("crashy", group="X", label="X", rule="x")\n    def f(ctx, ch):\n        raise ValueError("bad")\n')
        (self.ws / "chapters" / "01_introduction.md").write_text(CHAPTER, encoding="utf-8")
        checks = {c["id"]: c for c in run_quality_checks(self.cfg())["chapters"][0]["checks"]}
        self.assertEqual(checks["placeholder"]["state"], "bad")
        self.assertEqual(checks["dangling"]["count"], 1)       # Section 1.2 does not exist
        self.assertEqual(checks["first_person"]["state"], "bad")
        self.assertEqual(checks["table_caption"]["state"], "ok")
        self.assertEqual(checks["numbering"]["state"], "ok")
        self.assertEqual(checks["stacked"]["state"], "bad")    # "# 1." straight into "## 1.1"
        self.assertEqual(checks["crashy"]["state"], "error")
        self.assertEqual(checks["tone"]["state"], "na")

    def test_word_count_excludes_headings_tables_and_citations(self):
        (self.ws / "chapters" / "01_introduction.md").write_text("# Title words\n\nOne two three (Knuth, 1984).\n\n| a | b |\n", encoding="utf-8")
        self.assertEqual(get_adapter(self.cfg()).discover_chapters()[0].words, 3)

    def test_pdf_page_count_inside_compressed_stream(self):
        obj = zlib.compress(b"<< /Type /Pages /Kids [3 0 R] /Count 7 >>")
        data = b"%PDF-1.5\n1 0 obj\n<< /Length 9 >>\nstream\n" + obj + b"\nendstream\nendobj\n"
        self.assertEqual(pdf_page_count(data), 7)

    def test_citations(self):
        entries = {e["key"]: e for e in CitationService(self.cfg()).load_entries()}
        self.assertEqual(entries["knuth1984"]["status"], "verified")
        self.assertEqual(extract_citations("See [@turing1950].", "pandoc"), ["turing1950"])
        self.assertEqual(extract_citations(r"\parencite{a,b}", "latex"), ["a", "b"])


class TestCommentsAndTasks(Base):
    def setUp(self) -> None:
        super().setUp()
        self.rel = "chapters/01_introduction.md"
        self.raw = (self.ws / self.rel).read_text(encoding="utf-8")

    def test_anchor_from_rendered_selection_and_fuzzy_reanchor(self):
        cs = CommentService(self.cfg())
        sentence = next(l for l in self.raw.splitlines() if len(l) > 40 and not l.startswith("#"))
        plain = sentence.replace("**", "").replace("*", "")[5:45]
        code, out = cs.apply({"ch": 1, "action": "add", "file": self.rel, "quote": plain, "kind": "fix", "text": "tighten"})
        self.assertEqual(code, 200, out)
        c = out["comment"]
        self.assertEqual(cs.with_anchors(1)[0]["anchor"]["state"], "exact")
        (self.ws / self.rel).write_text(self.raw.replace(c["quote"], c["quote"][:-3] + "XYZ"), encoding="utf-8")
        self.assertEqual(cs.with_anchors(1)[0]["anchor"]["state"], "fuzzy")
        self.assertEqual(locate("completely different", c)["state"], "orphan")

    def test_full_closing_cycle_with_agents(self):
        cfg = self.cfg()
        cs, ts = CommentService(cfg), TaskService(cfg)
        quote = next(l for l in self.raw.splitlines() if len(l) > 40 and not l.startswith("#"))[:30]
        _, out = cs.apply({"ch": 1, "action": "add", "file": self.rel, "quote": quote, "kind": "fix", "text": "simplify"})
        cid = out["comment"]["id"]

        task = ts.create(workflow="close-comments", chapter=1)[1]
        self.assertEqual(task["role"], "proposal-drafter")
        self.assertEqual(task["comments"][0]["id"], cid)
        doc = {"task": task["id"], "kind": "proposals", "role": "proposal-drafter", "agent": {"name": "Agent Z"},
               "proposals": [{"comment_id": cid, "file": self.rel, "quote": quote, "replacement": "NEW TEXT", "rationale": "r"}]}
        self.write(task["output"], json.dumps(doc))
        ok, errs = ts.validate(task["id"])
        self.assertTrue(ok, errs)
        self.assertEqual(cs.queue()["items"][0]["status"], "addressed")
        self.assertEqual(next(t for t in ts.list() if t.get("workflow"))["status"], "done")  # parent closes itself

        # an agent cannot approve by editing the JSON: the seal would not verify
        self.assertEqual(cs.apply({"ch": 1, "id": cid, "action": "accept"})[0], 200)
        data = cs.load(1)
        data["comments"][0]["proposal"]["replacement"] = "SNEAKY"
        cs._save(1, data)
        self.assertEqual(cs.approved_changes(1), [])
        data["comments"][0]["proposal"]["replacement"] = "NEW TEXT"
        cs._save(1, data)
        self.assertEqual(len(cs.approved_changes(1)), 1)

        impl = ts.create(role="implementer", chapter=1)[0]
        self.assertEqual(impl["approved_changes"][0]["comment_id"], cid)
        self.write(impl["output"], json.dumps({"task": impl["id"], "kind": "applied", "role": "implementer",
                                               "agent": {"name": "Agent Z"}, "applied": [{"comment_id": cid}]}))
        ok, errs = ts.validate(impl["id"])
        self.assertFalse(ok)                                   # text not changed yet
        self.assertIn("not in", errs[0])
        (self.ws / self.rel).write_text(self.raw.replace(quote, "NEW TEXT", 1), encoding="utf-8")
        ok, errs = ts.validate(impl["id"])
        self.assertTrue(ok, errs)
        self.assertEqual(cs.queue()["items"][0]["status"], "applied")
        cs.apply({"ch": 1, "id": cid, "action": "status", "status": "resolved"})
        self.assertEqual(cs.queue()["items"], [])

    def test_author_suggestion_is_sealed_on_creation(self):
        cs = CommentService(self.cfg())
        quote = next(l for l in self.raw.splitlines() if len(l) > 40 and not l.startswith("#"))[:25]
        code, out = cs.apply({"ch": 1, "action": "add", "file": self.rel, "quote": quote, "kind": "suggest", "replacement": "Better."})
        self.assertEqual(code, 200, out)
        self.assertEqual(out["comment"]["status"], "approved")
        self.assertEqual(len(cs.approved_changes(1)), 1)

    def test_review_validation_and_agent_review_check(self):
        ts = TaskService(self.cfg())
        task = ts.create(role="tone-reviewer", chapter=1)[0]
        self.write(task["output"], json.dumps({"task": task["id"], "kind": "review", "role": "tone-reviewer", "agent": {"name": "A"},
                                               "summary": "s", "findings": [{"file": "elsewhere.md", "severity": "huge"}]}))
        ok, errs = ts.validate(task["id"])
        self.assertFalse(ok)
        self.assertTrue(any("independent" in e for e in errs))
        self.assertTrue(any("severity" in e for e in errs))
        self.write(task["output"], json.dumps({"task": task["id"], "kind": "review", "role": "tone-reviewer", "agent": {"name": "A"},
                                               "independent": True, "summary": "s",
                                               "findings": [{"file": self.rel, "line": 3, "severity": "warn", "problem": "too informal"}]}))
        ok, errs = ts.validate(task["id"])
        self.assertTrue(ok, errs)
        tone = next(c for c in run_quality_checks(self.cfg())["chapters"][0]["checks"] if c["id"] == "tone")
        self.assertEqual(tone["state"], "warn")
        time.sleep(0.01)
        (self.ws / self.rel).write_text(self.raw + "\nMore text.\n", encoding="utf-8")
        tone = next(c for c in run_quality_checks(self.cfg())["chapters"][0]["checks"] if c["id"] == "tone")
        self.assertEqual(tone["state"], "na")                  # stale after the text changed


class TestChangesAndPages(Base):
    def setUp(self) -> None:
        super().setUp()
        self.rel = "chapters/01_introduction.md"
        self.raw = (self.ws / self.rel).read_text(encoding="utf-8")
        self.old = next(l for l in self.raw.splitlines() if len(l) > 40 and not l.startswith("#"))[:30]
        self.write(".thesis/dialogue/CH1_PLAN.md", (self.ws / ".thesis/dialogue/CH1_PLAN.md").read_text())
        self.write(".thesis/proposals/proposals.json", json.dumps({
            "version": 1, "topics": [{"id": "t1", "thread": "CH1_PLAN.md", "q": "Q1", "title": "Wording"}],
            "items": [
                {"id": "A1", "topic": "t1", "file": self.rel, "old": self.old, "new": "Brand new start", "desc": "d", "status": "pending"},
                {"id": "A2", "topic": "t1", "file": self.rel, "old": "gone text", "new": self.raw.splitlines()[0][2:12],
                 "desc": "applied without review", "status": "applied"},
            ]}))

    def test_verdicts_decisions_seal_register_and_implementer(self):
        from atw.changes import ChangeService
        from atw.server import WorkbenchApp
        cs = ChangeService(self.cfg())
        items = {i["id"]: i for i in cs.load()["items"]}
        self.assertEqual((items["A1"]["verdict"], items["A1"]["anchor"]["state"]), ("pending", "exact"))
        self.assertEqual(items["A2"]["verdict"], "review")
        q = WorkbenchApp(self.ws).queue()
        self.assertEqual({i["id"] for i in q["items"] if i["source"] == "change"}, {"A1", "A2"})

        self.assertEqual(cs.apply({"action": "decide", "ids": ["A2"], "decision": "approved"})[0], 409)  # already applied
        self.assertEqual(cs.apply({"action": "review", "ids": ["A2"], "decision": "kept"})[0], 200)
        self.assertEqual(cs.apply({"action": "decide", "ids": ["A1"], "decision": "approved"})[0], 200)
        self.assertTrue(cs.load()["items"][0]["sealed"])
        # forging an approval by editing the file does not pass the seal
        data = json.loads((self.ws / ".thesis/proposals/proposals.json").read_text())
        data["items"][0]["new"] = "SNEAKY"
        (self.ws / ".thesis/proposals/proposals.json").write_text(json.dumps(data))
        self.assertEqual(cs.approved_for({self.rel}), [])
        data["items"][0]["new"] = "Brand new start"
        (self.ws / ".thesis/proposals/proposals.json").write_text(json.dumps(data))

        code, pv = cs.apply({"action": "register", "preview": True})
        self.assertEqual(code, 200)
        self.assertIn("approved A1", pv["preview"]["CH1_PLAN.md"])
        self.assertEqual(cs.apply({"action": "register"})[0], 200)
        th = DialogueService(self.cfg()).parse_thread(self.ws / ".thesis/dialogue/CH1_PLAN.md")
        self.assertTrue(th["turns"][-1]["sealed"])
        self.assertEqual(cs.counts()["to_register"], 0)

        ts = TaskService(self.cfg())
        impl = ts.create(role="implementer", chapter=1)[0]
        self.assertEqual(impl["approved_changes"][0]["change_id"], "A1")
        (self.ws / self.rel).write_text(self.raw.replace(self.old, "Brand new start", 1), encoding="utf-8")
        self.write(impl["output"], json.dumps({"task": impl["id"], "kind": "applied", "role": "implementer",
                                               "agent": {"name": "Z"}, "applied": [{"change_id": "A1"}]}))
        ok, errs = ts.validate(impl["id"])
        self.assertTrue(ok, errs)
        self.assertEqual({i["id"]: i["verdict"] for i in cs.load()["items"]}["A1"], "approved")

    def test_agent_proposals_without_comment_become_changes(self):
        from atw.changes import ChangeService
        ts = TaskService(self.cfg())
        task = ts.create(role="condenser", chapter=1)[0]
        self.write(task["output"], json.dumps({"task": task["id"], "kind": "proposals", "role": "condenser", "agent": {"name": "C"},
                                               "independent": True,
                                               "proposals": [{"file": self.rel, "quote": self.old, "replacement": "", "rationale": "cut"}]}))
        ok, errs = ts.validate(task["id"])
        self.assertTrue(ok, errs)
        new = [i for i in ChangeService(self.cfg()).load()["items"] if i.get("task") == task["id"]]
        self.assertEqual((len(new), new[0]["verdict"], new[0]["by"]), (1, "pending", "C"))

    def test_page_budget_uses_the_chapters_own_words_per_page(self):
        from atw.pages import budget, citation_share
        self.assertGreater(citation_share(["Text text text (Knuth, 1984) more text here."]), 0.2)
        toml = (self.ws / "thesis.toml").read_text() + '\n[format.pages]\ntargets = { default = [20, 25] }\naux = "build/ch{chapter}.aux"\naux_label = "endofchapter"\n'
        self.write("thesis.toml", toml.replace("[format]\n", "[format]\n", 1))
        self.write("build/ch1.aux", "\\newlabel{endofchapter}{{}{10}}\n")
        cfg = self.cfg()
        b = budget(cfg, 1, 3000, ["word " * 3000], [self.ws / self.rel])
        self.assertEqual((b["pdf_pages"], b["words_per_page"], b["words_fit"]), (10, 300, 7500))
        self.assertEqual(b["estimate_now"], 10.0)
        checks = {c["id"]: c for c in run_quality_checks(cfg)["chapters"][0]["checks"]}
        self.assertEqual(checks["pages"]["count"], 10)
        self.assertIn("without citations", checks["pages"]["note"])


class TestSigningKey(Base):
    def test_never_creates_a_second_key_silently(self):
        from atw.dialogue import SealKeyMissing
        missing = self.tmp / "nope.key"
        os.environ["ATW_SIGNING_KEY"] = str(missing)
        dlg = DialogueService(self.cfg())
        with self.assertRaises(SealKeyMissing):
            dlg.append_decision("CH1_PLAN.md", "", [{"id": "Q1", "state": "APPROVED"}])
        self.assertFalse(missing.exists())
        self.assertNotIn("Moderator Decision", (self.ws / ".thesis/dialogue/CH1_PLAN.md").read_text())
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(WorkbenchApp(self.ws)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        c = HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        c.request("POST", "/api/decide", body=json.dumps({"file": "CH1_PLAN.md", "decisions": [{"id": "Q1", "state": "APPROVED"}]}),
                  headers={"Content-Type": "application/json", "Host": "127.0.0.1"})
        r = c.getresponse()
        self.assertEqual(r.status, 400)
        self.assertIn("No signing key", json.loads(r.read())["error"])

    def test_require_key_path_ignores_the_default_location(self):
        os.environ.pop("ATW_SIGNING_KEY", None)
        toml = (self.ws / "thesis.toml").read_text().replace("sign_decisions = true", "sign_decisions = true\nrequire_key_path = true")
        self.write("thesis.toml", toml)
        from atw.dialogue import ModeratorSeal
        st = ModeratorSeal(self.cfg()).status()
        self.assertFalse(st["key_exists"])
        self.assertIn("key_path", st["key_path"])

    def test_two_tools_with_the_same_key_agree(self):
        p = self.ws / ".thesis/dialogue/CH1_PLAN.md"
        DialogueService(self.cfg()).append_decision("CH1_PLAN.md", "", [{"id": "Q1", "state": "APPROVED"}])
        other = load_config(self.ws)  # a second tool reading the same files with the same key
        q = next(q for q in DialogueService(other).parse_thread(p)["questions"] if q["id"] == "Q1")
        self.assertEqual((q["state"], q["authenticated"]), ("APPROVED", True))
        os.environ["ATW_SIGNING_KEY"] = str(self.tmp / "other.key")
        (self.tmp / "other.key").write_text("1" * 64)
        q = next(q for q in DialogueService(load_config(self.ws)).parse_thread(p)["questions"] if q["id"] == "Q1")
        self.assertFalse(q["authenticated"])                # a different key does not see the seal


class TestCache(Base):
    def test_answers_from_memory_and_refreshes_when_a_file_changes(self):
        app = WorkbenchApp(self.ws)
        first = app.state()
        self.assertIs(app.state(), first)                      # same object: answered from memory
        time.sleep(0.01)
        f = self.ws / "chapters" / "01_introduction.md"
        f.write_text(f.read_text() + "\nOne more sentence with several new words.\n")
        second = app.state()
        self.assertIsNot(second, first)
        self.assertGreater(second["stats"]["total_words"], first["stats"]["total_words"])


class TestPlanSeparation(Base):
    def test_engine_has_no_limits_of_its_own(self):
        ws = self.tmp / "bare"
        (ws / "chapters").mkdir(parents=True)
        (ws / "chapters" / "01_intro.md").write_text("# 1. Intro\n\nA very long sentence " + "word " * 80 + ".\n")
        cfg = load_config(ws)
        self.assertIsNone(cfg.default_word_target)
        self.assertIsNone(cfg.max_sentence_words)
        self.assertEqual(cfg.emphasis_words, [])
        checks = {c["id"]: c for c in run_quality_checks(cfg)["chapters"][0]["checks"]}
        for cid in ("long", "word_budget", "pages", "sections"):
            self.assertEqual(checks[cid]["state"], "ok", cid)

    def test_plan_file_sets_chapters_pages_words_narrative(self):
        self.write(".thesis/plan.toml", "[chapter_defaults]\npages = [20, 25]\nwords = [6000, 7500]\nsections = 5\n\n"
                   "[[chapters]]\nnumber = 9\npages = [10, 13]\nwords = [3000, 4000]\nnarrative = \"Concludes.\"\n")
        cfg = load_config(self.ws)
        self.assertEqual(cfg.plan_file, ".thesis/plan.toml")
        self.assertEqual((cfg.page_targets[0], cfg.page_targets[9]), ((20, 25), (10, 13)))
        self.assertEqual((cfg.word_target(1), cfg.word_target(9)), ((6000, 7500), (3000, 4000)))
        self.assertEqual((cfg.sections_for(1), cfg.spec(9)["narrative"]), (5, "Concludes."))
        task = TaskService(cfg).create(role="narrative-reviewer", chapter=9)[0]
        self.assertEqual((task["inputs"]["plan"], task["chapter_plan"]["narrative"]), (".thesis/plan.toml", "Concludes."))


class TestRolesCliI18n(Base):
    def test_roles_front_matter_and_export(self):
        meta, body = parse_front_matter("---\nname: x\ninputs: [a, b]\nindependent: false\n---\nDo it.\n")
        self.assertEqual((meta["name"], meta["inputs"], meta["independent"], body.strip()), ("x", ["a", "b"], False, "Do it."))
        roles, errors = load_roles(self.cfg())
        self.assertFalse(errors)
        self.assertIn("tone-reviewer", roles)
        files = export_roles(self.cfg(), "claude")
        text = (self.ws / ".claude/agents/tone-reviewer.md").read_text()
        self.assertTrue(text.startswith("---\nname: tone-reviewer\n"))
        self.assertIn("Workbench contract", text)
        self.assertEqual(len(files), len(roles))
        export_roles(self.cfg(), "skills")
        self.assertTrue((self.ws / ".agents/skills/tone-reviewer/SKILL.md").is_file())

    def test_init_and_cli(self):
        ws = self.tmp / "fresh"
        self.assertEqual(cmd_init(ws), 0)
        for rel in ("thesis.toml", "AGENTS.md", ".thesis/style/guide.json", ".thesis/tasks", ".thesis/plugins"):
            self.assertTrue((ws / rel).exists(), rel)
        self.assertEqual(main(["check", "--workspace", str(self.ws), "--chapter", "1"]), 0)
        self.assertEqual(main(["task", "new", "--role", "chapter-auditor", "--chapter", "1", "--workspace", str(self.ws)]), 0)

    def test_i18n_files_have_the_same_keys(self):
        en = json.loads((ROOT / "web/i18n/en.json").read_text())
        pt = json.loads((ROOT / "web/i18n/pt.json").read_text())
        self.assertEqual(set(en), set(pt))

    def test_engine_has_no_project_specific_names(self):
        # Tool names are always banned; add your own private terms (names, project, institution) locally with
        # ATW_PRIVATE_TERMS="term1,term2" so they never have to be written in this public repository.
        private = [t.strip().lower() for t in os.environ.get("ATW_PRIVATE_TERMS", "").split(",") if t.strip()]
        banned = tuple(["antigravity", "claude", "gemini", "opencode"] + private)
        for p in list((ROOT / "atw").rglob("*.py")) + list((ROOT / "web").rglob("*.js")) + list((ROOT / "atw/roles").rglob("*.md")):
            low = p.read_text(encoding="utf-8").lower()
            for b in banned:
                if b == "claude" and p.name in ("roles.py", "__main__.py"):
                    continue  # export target name for the .claude/agents folder
                self.assertFalse(b in low, f"{b} in {p}")


if __name__ == "__main__":
    unittest.main()
