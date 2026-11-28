"""Property tests: each property is checked on many generated inputs (fixed seeds, stdlib only, reproducible).
The requirement each class verifies is named in its docstring (REQ: …)."""
import hashlib
import json
import random
import re
import string
import tempfile
import unittest
from pathlib import Path

from atw import library, output
from atw.citations import _parse_bibtex
from atw.comments import CommentService, locate, text_shows
from atw.config import load_config
from atw.dialogue import ModeratorSeal

N = 300
ALPHABET = string.ascii_letters + string.digits + " .,;:-_&%$#{}~^\\áéíóúçãõ€—"


def rnd_text(r: random.Random, lo=1, hi=60) -> str:
    return "".join(r.choice(ALPHABET) for _ in range(r.randint(lo, hi)))


def ws_with_key() -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "key").write_text("e" * 64)
    (d / "thesis.toml").write_text(f'[agents]\nsign_decisions = true\nkey_path = "{d / "key"}"\n')
    return d


class SealProperties(unittest.TestCase):
    """REQ: RF-SEAL-02 — any change to a sealed block or payload breaks the seal; the untouched one verifies."""

    def test_block_tamper_is_detected(self):
        r = random.Random(1)
        seal = ModeratorSeal(load_config(ws_with_key()))
        for _ in range(N):
            body = "## Moderator Decision (Jane) — 2026-01-01 (on `Q1`)\n\n- **Decision on `Q1` (`APPROVED`):** " + rnd_text(r)
            signed = seal.sign("T.md", body)
            lines = signed.splitlines()
            self.assertTrue(seal.verify("T.md", lines))
            self.assertFalse(seal.verify("U.md", lines))            # the seal is bound to the thread
            i = r.randrange(0, len(body))
            ch = r.choice([c for c in ALPHABET if c != body[i] and c not in " \n"])
            tampered = (body[:i] + ch + body[i + 1:]) + signed[len(body):]
            if tampered.splitlines()[:-1] != lines[:-1]:
                self.assertFalse(seal.verify("T.md", tampered.splitlines()), (i, ch))

    def test_payload_tamper_is_detected(self):
        r = random.Random(2)
        seal = ModeratorSeal(load_config(ws_with_key()))
        for _ in range(N):
            payload = json.dumps([rnd_text(r, 1, 8), rnd_text(r), rnd_text(r)])
            mac = seal.sign_payload(payload)
            self.assertTrue(seal.verify_payload(payload, mac))
            other = payload[:-2] + ("x" if payload[-2] != "x" else "y") + payload[-1]
            self.assertFalse(seal.verify_payload(other, mac))

    def test_other_key_does_not_verify(self):
        a, b = ws_with_key(), ws_with_key()
        (b / "key").write_text("f" * 64)
        sa, sb = ModeratorSeal(load_config(a)), ModeratorSeal(load_config(b))
        self.assertFalse(sb.verify_payload("x", sa.sign_payload("x")))


class EscapingProperties(unittest.TestCase):
    """REQ: RF-OUT-02 RF-LIB-06 — LaTeX and BibTeX output never carries an unescaped special character."""

    SPECIAL = "&%$#_"

    def test_latex_escape(self):
        r = random.Random(3)
        for _ in range(N):
            s = rnd_text(r)
            e = output.latex_escape(s)
            self.assertIsNone(re.search(r"(?<!\\)[&%$#_]", e), (s, e))
            self.assertEqual(re.sub(r"\\([&%$#_])", r"\1", e), s)   # nothing else changes

    def test_bibtex_export_escapes_and_keeps_keys(self):
        r = random.Random(4)
        for _ in range(60):
            items = library.assign_keys([{"type": "article-journal", "title": rnd_text(r),
                                          "author": [{"family": rnd_text(r, 1, 10).strip() or "X", "given": "A"}],
                                          "issued": {"date-parts": [[r.randint(1900, 2030)]]}} for _ in range(r.randint(1, 8))])
            bib = library.csl_to_bibtex(items)
            for m in re.finditer(r"^\s*(author|title|journal) = \{(.*)\}", bib, re.M):
                self.assertIsNone(re.search(r"(?<!\\)[&%$#_]", m.group(2)), m.group(0))
            self.assertEqual([e["key"] for e in _parse_bibtex(bib)], [i["id"] for i in items])


class KeyProperties(unittest.TestCase):
    """REQ: RF-LIB-05 — synced citation keys are unique; a manager's own key is kept."""

    def test_unique_and_stable(self):
        r = random.Random(5)
        fams = ["Smith", "Silva", "Ng", "", "Müller"]
        for _ in range(N):
            items = []
            for _ in range(r.randint(1, 40)):
                it = {"title": rnd_text(r, 1, 10), "issued": {"date-parts": [[r.choice([2019, 2020])]]}}
                if r.random() < 0.8:
                    it["author"] = [{"family": r.choice(fams)}]
                if r.random() < 0.1:
                    it["citation-key"] = f"own{r.randint(0, 3)}"
                items.append(it)
            # managers' own keys are unique within one library
            seen_own = set()
            for it in items:
                if it.get("citation-key") in seen_own:
                    del it["citation-key"]
                elif it.get("citation-key"):
                    seen_own.add(it["citation-key"])
            out = library.assign_keys(items)
            keys = [i["id"] for i in out]
            self.assertEqual(len(keys), len(set(keys)), keys)
            for a, b in zip(items, out):
                if a.get("citation-key"):
                    self.assertEqual(b["id"], a["citation-key"])
                self.assertRegex(b["id"], r"^[A-Za-z0-9]+$")


class TitleProperties(unittest.TestCase):
    """REQ: RF-OUT-02 — the cover title is split into at most three lines and no word is lost or reordered."""

    def test_split_title(self):
        r = random.Random(6)
        for _ in range(N):
            words = [rnd_text(r, 1, 12).replace(" ", "") or "w" for _ in range(r.randint(1, 14))]
            title = " ".join(words)
            a, b, c = output.split_title(title)
            self.assertEqual(" ".join(x for x in (a, b, c) if x).split(), title.split())


class TemplateApplyProperties(unittest.TestCase):
    """REQ: RF-OUT-02 — applying a template never overwrites a file the author already has, and applying twice
    changes nothing but the generated chapter list."""

    def test_never_overwrites(self):
        r = random.Random(7)
        src = Path(output.BUILTIN / "uminho-phd" / "latex")
        rels = [p.relative_to(src) for p in src.rglob("*") if p.is_file() and p.name != "dissertation.tex"]
        for _ in range(15):
            d = Path(tempfile.mkdtemp())
            (d / "thesis.toml").write_text('[project]\ntitle = "T"\nauthor = "A"\n[output]\ntemplate = "uminho-phd"\n')
            mine = r.sample(rels, r.randint(1, 8))
            for rel in mine:
                p = d / "latex" / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"MINE " + str(rel).encode())
            cfg = load_config(d)
            self.assertTrue(output.apply(cfg)[0])
            snap = {p: p.read_bytes() for p in (d / "latex").rglob("*") if p.is_file()}
            for rel in mine:
                self.assertEqual((d / "latex" / rel).read_bytes(), b"MINE " + str(rel).encode())
            self.assertTrue(output.apply(cfg)[0])
            self.assertEqual({p: p.read_bytes() for p in (d / "latex").rglob("*") if p.is_file()}, snap)


class TextShowsProperties(unittest.TestCase):
    """REQ: RF-COM-07 RF-CHG-04 — "applied" is accepted only when the replacement is in the text and the replaced
    passage is gone (or is part of the replacement)."""

    def test_definition(self):
        r = random.Random(8)
        for _ in range(N):
            old, new = rnd_text(r, 5, 20), r.choice(["", rnd_text(r, 5, 20)])
            before = rnd_text(r) + old + rnd_text(r)
            after = before.replace(old, new, 1)
            if old in new or old not in after:
                self.assertTrue(text_shows(after, old, new))
            if old not in new and new not in before:
                self.assertFalse(text_shows(before, old, new))


class AnchorProperties(unittest.TestCase):
    """REQ: RF-COM-02 — a comment re-anchors exactly while its passage is unique, fuzzily after small edits and
    becomes an orphan when the passage is gone."""

    def test_anchoring(self):
        r = random.Random(9)
        words = ["soil", "water", "sensor", "drift", "plot", "yield", "season", "farm", "crop", "root"]
        for _ in range(100):
            quote = " ".join(r.choice(words) for _ in range(8)) + " unique-marker"
            text = "Intro text here. " + quote + " Closing text."
            c = {"quote": quote, "prefix": "Intro text here. ", "suffix": " Closing text.", "pos": 17}
            self.assertEqual(locate(text, c)["state"], "exact")
            edited = text.replace("unique-marker", "unique-markers")
            self.assertIn(locate(edited, c)["state"], ("fuzzy", "exact"))
            self.assertEqual(locate("Something else entirely.", c)["state"], "orphan")


if __name__ == "__main__":
    unittest.main()
