"""Conformance: the real ChangeService follows verify/ChangeLifecycle.tla for both kinds of proposal (replacement
and deletion) and every sequence of up to 4 actions. REQ: RF-CHG-02 RF-CHG-03 RF-CHG-04 RF-CHG-05 RF-CHG-06"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "verify"))
from tlc import model_table, thaw_record, tlc_available  # noqa: E402

from atw.changes import ChangeService  # noqa: E402
from atw.config import load_config  # noqa: E402

OLD = "The quick brown fox jumps over the lazy dog."
NEW = "A swift auburn fox leaps over a sleepy hound."
TEXT = f"# 1 Chapter\n\nIntro sentence here. {OLD} Closing sentence here.\n"
THREAD = "# CH1_PLAN\n\n## Turn 1 — Agent (M) — 2026-01-01\n\n| Q1 | Topic | OPEN | Jane | x |\n"


class Harness:
    REL = "chapters/01_ch.md"

    def __init__(self):
        d = Path(tempfile.mkdtemp())
        key = d / "key"
        key.write_text("c" * 64)
        (d / "thesis.toml").write_text(
            f'[agents]\ndialogue_dir = "dlg"\ndialogue_profile = "en"\nproposals_file = "props.json"\n'
            f'moderator_name = "Jane"\nsign_decisions = true\nkey_path = "{key}"\n', encoding="utf-8")
        (d / "chapters").mkdir()
        (d / "dlg").mkdir()
        self.ws, self.svc = d, ChangeService(load_config(d))

    def reset(self, kind: str):
        (self.ws / self.REL).write_text(TEXT, encoding="utf-8")
        (self.ws / "dlg" / "CH1_PLAN.md").write_text(THREAD, encoding="utf-8")
        self.new = "" if kind == "empty" else NEW
        (self.ws / "props.json").write_text(json.dumps({"version": 1, "topics": [
            {"id": "t1", "thread": "CH1_PLAN.md", "q": "Q1", "title": "T"}], "items": [
            {"id": "P-1", "topic": "t1", "file": self.REL, "old": OLD, "new": self.new, "status": "pending",
             "by": "agent"}]}), encoding="utf-8")

    def item(self):
        return json.loads((self.ws / "props.json").read_text())["items"][0]

    def raw(self):
        return (self.ws / self.REL).read_text(encoding="utf-8")

    def do(self, x):
        a, s = x["a"], x["s"]
        if a == "decide":
            self.svc.apply({"action": "decide", "ids": ["P-1"], "decision": s})
        elif a == "review":
            self.svc.apply({"action": "review", "ids": ["P-1"], "decision": s})
        elif a == "register":
            self.svc.apply({"action": "register"})
        elif a == "edit":
            if OLD in self.raw():
                (self.ws / self.REL).write_text(self.raw().replace(OLD, self.new, 1))
        elif a == "apply":
            self.svc.mark_applied("P-1", "T-1", "implementer")
        elif a == "tamper":
            data = json.loads((self.ws / "props.json").read_text())
            data["items"][0]["old"] += " (edited by an agent)"
            (self.ws / "props.json").write_text(json.dumps(data))

    def observe(self):
        it = self.item()
        return (it.get("status"), it.get("decision") or "none", bool(it.get("registered")),
                self.svc.sealed(it), OLD in self.raw())


@unittest.skipUnless(tlc_available(), "TLC (tla2tools) not installed — run verify/run.sh on a machine with TLC")
class ChangeConformance(unittest.TestCase):
    def test_every_sequence_matches_the_model(self):
        rows = model_table("ChangeLifecycle", {"ApproveNeedsAnchor": "TRUE", "MaxSteps": "0"})
        self.assertGreater(len(rows), 20000)
        h = Harness()
        mismatches = []
        for raw in rows:
            kind, xs, status, decision, registered, sealed, quote_in = thaw_record(raw)
            h.reset(kind)
            for x in xs:
                h.do(x)
            got = h.observe()
            want = (status, decision, registered, sealed, quote_in)
            if got != want:
                mismatches.append((kind, [f"{x['a']}:{x['s']}" for x in xs], want, got))
        self.assertEqual(mismatches[:5], [], f"{len(mismatches)} sequences differ from the model")

    def test_rule_in_code_is_the_proved_one(self):
        cfg = (Path(__file__).resolve().parent.parent / "verify" / "ChangeLifecycle.cfg").read_text()
        self.assertIn("ApproveNeedsAnchor = TRUE", cfg)


if __name__ == "__main__":
    unittest.main()
