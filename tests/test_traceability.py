"""Traceability gate. REQ: RNF-VER-01"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "verify"))
import trace  # noqa: E402


class Traceability(unittest.TestCase):
    def test_every_requirement_is_verified_and_every_link_resolves(self):
        reqs = trace.load()
        self.assertGreater(len(reqs), 100)
        self.assertEqual(trace.problems(reqs), [])

    def test_document_is_current(self):
        self.assertTrue(trace.DOC.is_file(), "run python3 verify/trace.py")
        self.assertEqual(trace.DOC.read_text(encoding="utf-8"), trace.render(trace.load()),
                         "docs/REQUIREMENTS.md is stale — run python3 verify/trace.py")


if __name__ == "__main__":
    unittest.main()
