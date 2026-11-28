"""Conformance: the real TaskService follows verify/TaskValidation.tla — an agent output takes effect once, a done
task stays done — for every sequence of up to 5 writes and validations. REQ: RF-TSK-04 RF-TSK-05"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "verify"))
from tlc import model_table, thaw_record, tlc_available  # noqa: E402

from atw.config import load_config  # noqa: E402
from atw.tasks import TaskService  # noqa: E402

TEXT = "# 1 Chapter\n\nIntro sentence here. The quick brown fox jumps over the lazy dog. Closing.\n"


class Harness:
    def __init__(self):
        d = Path(tempfile.mkdtemp())
        (d / "thesis.toml").write_text('[format]\nchapters_glob = "chapters/*.md"\n[agents]\nproposals_file = "props.json"\n',
                                       encoding="utf-8")
        (d / "chapters").mkdir()
        (d / "chapters" / "01_ch.md").write_text(TEXT, encoding="utf-8")
        self.ws = d

    def reset(self):
        for f in list((self.ws / ".thesis").rglob("*.json")) if (self.ws / ".thesis").exists() else []:
            f.unlink()
        (self.ws / "props.json").unlink(missing_ok=True)
        self.ts = TaskService(load_config(self.ws))
        self.task = self.ts.create(role="condenser", chapter=1)[0]

    def write(self, valid: bool):
        doc = {"task": self.task["id"], "kind": "proposals", "role": "condenser", "agent": {"name": "A"}, "independent": True,
               "proposals": [{"file": "chapters/01_ch.md", "quote": "The quick brown fox jumps over the lazy dog."
                              if valid else "text that is not in the chapter", "replacement": "A fox jumps."}]}
        out = self.ws / self.task["output"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc), encoding="utf-8")

    def do(self, x):
        if x == "write-valid":
            self.write(True)
        elif x == "write-invalid":
            self.write(False)
        else:
            self.ts.validate(self.task["id"])

    def observe(self):
        status = self.ts.get(self.task["id"]).get("status")
        p = self.ws / "props.json"
        effects = len(json.loads(p.read_text())["items"]) if p.exists() else 0
        return status, effects


@unittest.skipUnless(tlc_available(), "TLC (tla2tools) not installed — run verify/run.sh on a machine with TLC")
class TaskConformance(unittest.TestCase):
    def test_every_sequence_matches_the_model(self):
        rows = model_table("TaskValidation", {"DoneIsFinal": "TRUE", "MaxSteps": "0"})
        self.assertGreater(len(rows), 300)
        h = Harness()
        mismatches = []
        for raw in rows:
            xs, status, effects = thaw_record(raw)
            h.reset()
            for x in xs:
                h.do(x)
            got = h.observe()
            if got != (status, effects):
                mismatches.append((list(xs), (status, effects), got))
        self.assertEqual(mismatches[:5], [], f"{len(mismatches)} sequences differ from the model")


if __name__ == "__main__":
    unittest.main()
