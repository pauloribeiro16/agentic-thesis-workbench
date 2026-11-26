"""Fast unit & HTTP integration tests for Agentic Thesis Workbench (<1s total)."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from atw.__main__ import cmd_init
from atw.citations import CitationService, extract_citations
from atw.config import load_config
from atw.dialogue import DialogueService
from atw.formats import FormatAdapter
from atw.quality import run_quality_checks
from atw.server import WorkbenchApp, make_handler

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_WS = REPO_ROOT / "examples" / "sample-thesis"


class TestWorkbench(unittest.TestCase):
    def test_sample_thesis_config_and_chapters(self) -> None:
        cfg = load_config(SAMPLE_WS)
        self.assertEqual(cfg.title, "Sample Doctoral Dissertation")
        self.assertEqual(cfg.format_adapter, "markdown")
        chapters = FormatAdapter(cfg).discover_chapters(include_content=True)
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0].number, 1)
        self.assertGreater(chapters[0].words, 10)

    def test_citations_bibtex_and_csl_json(self) -> None:
        cfg = load_config(SAMPLE_WS)
        entries = CitationService(cfg).load_entries()
        by_key = {e["key"]: e for e in entries}
        self.assertIn("knuth1984", by_key)
        self.assertEqual(by_key["knuth1984"]["status"], "verified")
        self.assertEqual(by_key["popper1959"]["status"], "bib_only")

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "thesis.toml").write_text(
                '[citations]\nprovider = "csl-json"\ncsl_file = "refs.json"\nsyntax = "pandoc"\n',
                encoding="utf-8",
            )
            (ws / "refs.json").write_text(
                json.dumps([{"id": "turing1950", "title": "Computing Machinery", "author": [{"given": "Alan", "family": "Turing"}], "issued": {"date-parts": [[1950]]}}]),
                encoding="utf-8",
            )
            csl_entries = CitationService(load_config(ws)).load_entries()
            self.assertEqual(len(csl_entries), 1)
            self.assertEqual(csl_entries[0]["key"], "turing1950")
            self.assertEqual(extract_citations("See [@turing1950].", syntax="pandoc"), ["turing1950"])

    def test_quality_checks_and_glossary(self) -> None:
        cfg = load_config(SAMPLE_WS)
        chapters = FormatAdapter(cfg).discover_chapters(include_content=True)
        report = run_quality_checks(cfg, chapters, CitationService(cfg))
        self.assertEqual(report["style_guide_entries"], 1)
        checks = {c["id"]: c for c in report["chapters"][0]["checks"]}
        self.assertEqual(checks["placeholder"]["state"], "ok")
        self.assertEqual(checks["narrative"]["state"], "na")
        self.assertEqual(checks["tone"]["state"], "na")

    def test_model_agnostic_dialogue_and_hmac_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "thesis"
            shutil.copytree(SAMPLE_WS, ws)
            key_file = Path(tmp) / "mod.key"
            os.environ["ATW_SIGNING_KEY"] = str(key_file)
            try:
                cfg = load_config(ws)
                dlg = DialogueService(cfg)
                threads = dlg.list_threads()
                self.assertEqual(len(threads), 1)
                self.assertEqual(threads[0]["agents"], ["Reviewer A (Model Alpha)"])
                self.assertEqual(threads[0]["questions"][0]["state"], "AGENT_CONSENSUS")

                ok, msg = dlg.append_decision(
                    "CH1_PLAN.md",
                    threads[0]["sha"],
                    [{"id": "Q1", "state": "APPROVED", "note": "Approved in test"}],
                )
                self.assertTrue(ok, msg)

                updated = dlg.list_threads()[0]
                self.assertEqual(updated["questions"][0]["state"], "APPROVED")
                self.assertTrue(updated["questions"][0]["authenticated"])

                # Conflict detection with stale SHA
                ok2, msg2 = dlg.append_decision(
                    "CH1_PLAN.md",
                    threads[0]["sha"],
                    [{"id": "Q1", "state": "APPROVED", "note": "Stale"}],
                )
                self.assertFalse(ok2)
                self.assertIn("Conflict", msg2)
            finally:
                os.environ.pop("ATW_SIGNING_KEY", None)

    def test_init_scaffolds_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "new-thesis"
            rc = cmd_init(ws)
            self.assertEqual(rc, 0)
            self.assertTrue((ws / "thesis.toml").is_file())
            self.assertTrue((ws / "AGENTS.md").is_file())
            self.assertTrue((ws / ".thesis/style/guide.json").is_file())

    def test_http_standalone_and_second_brain_shells(self) -> None:
        os.environ["ATW_QUIET"] = "1"
        for mode, expected_nav in (("standalone", 'src="nav.js"'), ("second-brain", 'src="/nav.js"')):
            app = WorkbenchApp(SAMPLE_WS, host_shell=mode)
            srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
            port = srv.server_address[1]
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            try:
                html = urlopen(f"http://127.0.0.1:{port}/").read().decode("utf-8")
                self.assertIn(expected_nav, html)
                st = json.loads(urlopen(f"http://127.0.0.1:{port}/api/state").read().decode("utf-8"))
                self.assertEqual(st["host_shell"], mode)
                self.assertEqual(st["stats"]["chapters"], 1)
                summary = json.loads(urlopen(f"http://127.0.0.1:{port}/api/summary").read().decode("utf-8"))
                self.assertEqual(summary["stats"]["questions_waiting"], 1)
                etag = json.loads(urlopen(f"http://127.0.0.1:{port}/api/etag").read().decode("utf-8"))
                self.assertIn("etag", etag)
            finally:
                srv.shutdown()
                srv.server_close()


if __name__ == "__main__":
    unittest.main()
