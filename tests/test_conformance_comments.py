"""Conformance: the real CommentService follows verify/CommentLifecycle.tla for every sequence of up to 4 actions
(author, agent and implementer). REQ: RF-COM-03 RF-COM-04 RF-COM-05 RF-COM-06 RF-COM-07"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "verify"))
from tlc import model_table, thaw_record, tlc_available  # noqa: E402

from atw.comments import CommentService  # noqa: E402
from atw.config import load_config  # noqa: E402

QUOTE = "The quick brown fox jumps over the lazy dog."
REPL = "A swift auburn fox leaps over a sleepy hound."
TEXT = f"# 1 Chapter\n\n## 1.1 Section\n\nIntro sentence here. {QUOTE} Closing sentence here.\n"


def workspace() -> Path:
    d = Path(tempfile.mkdtemp())
    key = d / "key"
    key.write_text("b" * 64)
    (d / "thesis.toml").write_text(
        f'[format]\nchapters_glob = "chapters/*.md"\n[agents]\ncomments_dir = "cm"\nmoderator_name = "Jane"\n'
        f'sign_decisions = true\nkey_path = "{key}"\n', encoding="utf-8")
    (d / "chapters").mkdir()
    return d


class Harness:
    REL = "chapters/01_ch.md"

    def __init__(self, ws: Path):
        self.ws, self.cs = ws, CommentService(load_config(ws))

    def reset(self):
        (self.ws / self.REL).write_text(TEXT, encoding="utf-8")
        for f in (self.ws / "cm").glob("*.json") if (self.ws / "cm").is_dir() else []:
            f.unlink()
        _, out = self.cs.apply({"ch": 1, "action": "add", "file": self.REL, "quote": QUOTE, "kind": "fix", "text": "t"})
        self.cid = out["comment"]["id"]

    def comment(self):
        return next(c for c in self.cs.load(1)["comments"] if c["id"] == self.cid)

    def raw(self):
        return (self.ws / self.REL).read_text(encoding="utf-8")

    def do(self, x):
        a, s = x["a"], x["s"]
        if a == "status":
            self.cs.apply({"ch": 1, "action": "status", "id": self.cid, "status": s})
        elif a == "accept":
            self.cs.apply({"ch": 1, "action": "accept", "id": self.cid})
        elif a == "propose":
            if self.raw().count(QUOTE) == 1:  # task validation: the quote must appear exactly once
                self.cs.set_proposal(1, self.cid, {"quote": QUOTE, "replacement": "" if s == "empty" else REPL},
                                     "T-1", "agent")
        elif a == "edit":
            c = self.comment()
            if c.get("proposal") and QUOTE in self.raw():
                (self.ws / self.REL).write_text(self.raw().replace(QUOTE, c["proposal"]["replacement"], 1))
        elif a == "apply":
            self.cs.mark_applied(1, self.cid, "T-2", "implementer")
        elif a == "tamper":
            data = self.cs.load(1)
            c = next(c for c in data["comments"] if c["id"] == self.cid)
            if c.get("proposal"):
                c["proposal"]["quote"] = c["proposal"]["quote"] + " (edited by an agent)"
                self.cs._save(1, data)

    def observe(self):
        c = self.comment()
        return c["status"], self.cs._proposal_sealed(c), QUOTE in self.raw()


@unittest.skipUnless(tlc_available(), "TLC (tla2tools) not installed — run verify/run.sh on a machine with TLC")
class CommentConformance(unittest.TestCase):
    def test_every_sequence_matches_the_model(self):
        rows = model_table("CommentLifecycle", {"TextRule": '"passage-changed"', "MaxSteps": "0"})
        self.assertGreater(len(rows), 7000)
        h = Harness(workspace())
        mismatches = []
        for raw in rows:
            xs, status, sealed, quote_in = thaw_record(raw)
            h.reset()
            for x in xs:
                h.do(x)
            got = h.observe()
            if got != (status, sealed, quote_in):
                mismatches.append(([f"{x['a']}:{x['s']}" for x in xs], (status, sealed, quote_in), got))
        self.assertEqual(mismatches[:5], [], f"{len(mismatches)} sequences differ from the model")

    def test_text_rule_in_code_is_the_proved_one(self):
        cfg = (Path(__file__).resolve().parent.parent / "verify" / "CommentLifecycle.cfg").read_text()
        self.assertEqual(re.search(r'TextRule\s*=\s*"([^"]+)"', cfg).group(1), "passage-changed")


if __name__ == "__main__":
    unittest.main()
