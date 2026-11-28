"""Conformance: the real DialogueService gives, for every thread of up to 3 writes, exactly the result of the
TLA+ model verify/Governance.tla (whose invariants TLC proves). REQ: RF-GOV-01 RF-GOV-02 RF-GOV-03 RF-GOV-04 RF-GOV-05"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "verify"))
from tlc import model_table, thaw_record, tlc_available  # noqa: E402

from atw.config import load_config  # noqa: E402
from atw.dialogue import AUTHOR_ONLY_STATES, DialogueService, ModeratorSeal  # noqa: E402

AUTHOR_ONLY_TLA = "{" + ", ".join(f'"{s}"' for s in sorted(AUTHOR_ONLY_STATES)) + "}"


def make_workspace(signing: bool) -> Path:
    d = Path(tempfile.mkdtemp())
    key = d / "key"
    key.write_text("a" * 64)
    (d / "thesis.toml").write_text(
        f'[agents]\ndialogue_dir = "dlg"\ndialogue_profile = "en"\nmoderator_name = "Jane"\n'
        f'sign_decisions = {"true" if signing else "false"}\nkey_path = "{key}"\n', encoding="utf-8")
    (d / "dlg").mkdir()
    return d


def thread_text(ws: Path, writes, name: str) -> str:
    cfg = load_config(ws)
    seal = ModeratorSeal(cfg)
    key = Path(cfg.key_path).read_bytes().strip()
    blocks = ["# Thread\n"]
    for i, w in enumerate(writes, 1):
        date = f"2026-01-{i:02d}"
        if w["kind"] == "agent":
            blocks.append(f"## Turn {i} — Agent (Model) — {date}\n\n| # | Topic | State | To | Proposal |\n"
                          f"|---|---|---|---|---|\n| Q1 | Topic | {w['st']} | Jane | x |\n")
        else:
            body = f"## Moderator Decision (Jane) — {date} (on `Q1`)\n\n- **Decision on `Q1` (`{w['st']}`):** note"
            if w["sealed"]:
                body += f"\n\n<!-- moderator: v1 {seal.mac(name, body.splitlines(), key)} -->"
            blocks.append(body + "\n")
    return "\n".join(blocks)


@unittest.skipUnless(tlc_available(), "TLC (tla2tools) not installed — run verify/run.sh on a machine with TLC")
class GovernanceConformance(unittest.TestCase):
    def check(self, signing: bool):
        rows = model_table("Governance", {"Signing": "TRUE" if signing else "FALSE",
                                          "AuthorOnly": AUTHOR_ONLY_TLA, "MaxWrites": "0"})
        self.assertGreater(len(rows), 3000)
        ws = make_workspace(signing)
        svc = DialogueService(load_config(ws))
        mismatches = []
        for raw in rows:
            writes, state, auth, claims = thaw_record(raw)
            path = ws / "dlg" / "T.md"
            path.write_text(thread_text(ws, writes, "T.md"), encoding="utf-8")
            th = svc.parse_thread(path)
            q = next((x for x in th["questions"] if x["id"] == "Q1"),
                     {"state": "OPEN", "authenticated": False, "unauthorized_claims": []})
            got = (q["state"], q["authenticated"], len(q["unauthorized_claims"]))
            if got != (state, auth, claims):
                mismatches.append((writes, (state, auth, claims), got))
        self.assertEqual(mismatches[:5], [], f"{len(mismatches)} threads differ from the model")

    def test_code_constant_is_the_proved_one(self):
        """The set of author-only states in the code is the one TLC proved (Governance_signed/unsigned.cfg)."""
        import re
        for cfg in ("Governance_signed.cfg", "Governance_unsigned.cfg"):
            text = (Path(__file__).resolve().parent.parent / "verify" / cfg).read_text()
            proved = set(re.findall(r'"([A-Z_]+)"', re.search(r"AuthorOnly\s*=\s*\{([^}]*)\}", text).group(1)))
            self.assertEqual(proved, AUTHOR_ONLY_STATES, cfg)

    def test_signed(self):
        self.check(True)

    def test_unsigned(self):
        self.check(False)


if __name__ == "__main__":
    unittest.main()
