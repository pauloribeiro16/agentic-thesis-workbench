"""Templates (LaTeX / Word base) and the Zotero / Mendeley connectors — no network: HTTP is faked."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from atw import library, output
from atw.citations import CitationService
from atw.config import load_config


def workspace(toml: str) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "thesis.toml").write_text(toml, encoding="utf-8")
    return d


class TemplateTests(unittest.TestCase):
    TOML = """
[project]
title = "Adaptive Irrigation Scheduling from Low-Cost Soil Sensors & More"
author = "Jane Researcher"
[output]
base = "latex"
template = "uminho-phd"
[template]
supervisor = "Prof. A"
"""

    def test_builtin_template_is_listed(self):
        cfg = load_config(workspace(self.TOML))
        t = output.list_templates(cfg)["uminho-phd"]
        self.assertTrue(t["ready"]["latex"])
        self.assertFalse(t["ready"]["word"])

    def test_latex_apply_fills_fields_and_keeps_author_edits(self):
        ws = workspace(self.TOML)
        cfg = load_config(ws)
        ok, msg = output.apply(cfg)
        self.assertTrue(ok, msg)
        main = (ws / "latex" / "dissertation.tex").read_text()
        self.assertIn(r"\thesisauthor{Jane Researcher}", main)
        self.assertIn(r"\supervisor{Prof. A}", main)
        self.assertIn(r"\&", main)  # LaTeX special characters escaped
        self.assertIn(r"\input{chapters/1-Introduction}", main)
        self.assertNotIn("{{", main)
        # the author edits the main file and adds a chapter: a second apply refreshes only the chapter list
        (ws / "latex" / "dissertation.tex").write_text(main.replace("Prof. A", "Prof. B"))
        (ws / "latex" / "chapters" / "2-Background.tex").write_text(r"\chapter{Background}")
        ok, _ = output.apply(cfg)
        main2 = (ws / "latex" / "dissertation.tex").read_text()
        self.assertIn("Prof. B", main2)
        self.assertIn(r"\input{chapters/2-Background}", main2)

    def test_example_chapter_not_added_to_existing_thesis(self):
        ws = workspace(self.TOML)
        (ws / "latex" / "chapters").mkdir(parents=True)
        (ws / "latex" / "chapters" / "01-Mine.tex").write_text(r"\chapter{Mine}")
        output.apply(load_config(ws))
        self.assertFalse((ws / "latex" / "chapters" / "1-Introduction.tex").exists())

    def test_word_base_needs_the_docx_then_fills_properties(self):
        ws = workspace(self.TOML)
        cfg = load_config(ws)
        ok, msg = output.apply(cfg, base="word")
        self.assertFalse(ok)
        self.assertIn("word/template.docx", msg)
        tdir = ws / ".thesis" / "templates" / "uminho-phd" / "word"
        tdir.mkdir(parents=True)
        with zipfile.ZipFile(tdir / "template.docx", "w") as z:
            z.writestr("docProps/core.xml", '<?xml version="1.0"?><cp:coreProperties xmlns:cp="x" xmlns:dc="y">'
                                            "<dc:title></dc:title><cp:lastModifiedBy>Someone Else</cp:lastModifiedBy>"
                                            "</cp:coreProperties>")
            z.writestr("word/document.xml", "<w:document><w:t>{{author}} — {{programme}}</w:t></w:document>")
        ok, msg = output.apply(load_config(ws), base="word")
        self.assertTrue(ok, msg)
        with zipfile.ZipFile(ws / "word" / "thesis.docx") as z:
            core = z.read("docProps/core.xml").decode()
            doc = z.read("word/document.xml").decode()
        self.assertIn("<dc:creator>Jane Researcher</dc:creator>", core)
        self.assertNotIn("Someone Else", core)
        self.assertIn("Jane Researcher —", doc)

    def test_unknown_template(self):
        ok, msg = output.apply(load_config(workspace(self.TOML)), template="nope")
        self.assertFalse(ok)


class FakeHTTP:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        return self.pages.pop(0)


class LibraryTests(unittest.TestCase):
    def test_zotero_local_sync_paginates_and_writes_csl_and_bib(self):
        ws = workspace('[citations]\nprovider = "zotero"\ncsl_file = "references.json"\nbib_export = "latex/references.bib"\n')
        page1 = [{"id": "local/AB", "type": "article-journal", "title": "Soil & Water",
                  "author": [{"family": "Almeida", "given": "Rita"}], "issued": {"date-parts": [[2021]]}},
                 {"id": "local/AC", "type": "note"}]
        page2 = [{"id": "local/AD", "type": "book", "title": "Other", "author": [{"family": "Almeida", "given": "R"}],
                  "issued": {"date-parts": [[2021]]}, "citation-key": "almeidaBook"}]
        fake = FakeHTTP([(200, {"total-results": "150"}, json.dumps(page1).encode()),
                         (200, {"total-results": "150"}, json.dumps({"items": page2}).encode())])
        meta = library.sync(load_config(ws), fetch=fake)
        self.assertEqual(meta["count"], 2)
        self.assertTrue(fake.calls[0][0].startswith("http://127.0.0.1:23119/api/users/0/items/top?format=csljson"))
        self.assertIn("start=100", fake.calls[1][0])
        items = json.loads((ws / "references.json").read_text())
        self.assertEqual([i["id"] for i in items], ["Almeida2021", "almeidaBook"])
        bib = (ws / "latex" / "references.bib").read_text()
        self.assertIn("@article{Almeida2021,", bib)
        self.assertIn(r"title = {{Soil \& Water}}", bib)
        # the workbench reads the synced library as its bibliography
        entries = CitationService(load_config(ws)).load_entries()
        self.assertIn("Almeida2021", {e["key"] for e in entries})

    def test_zotero_web_needs_key(self):
        ws = workspace('[citations]\nprovider = "zotero"\n[citations.zotero]\nmode = "web"\nlibrary_id = "123"\napi_key_env = "ATW_TEST_NO_SUCH_VAR"\n')
        with self.assertRaises(library.LibraryError):
            library.sync(load_config(ws), fetch=FakeHTTP([]))

    def test_zotero_local_403_explains_setting(self):
        ws = workspace('[citations]\nprovider = "zotero"\n')
        with self.assertRaises(library.LibraryError) as cm:
            library.sync(load_config(ws), fetch=FakeHTTP([(403, {}, b"")]))
        self.assertIn("Allow other applications", str(cm.exception))

    def test_mendeley_api_follows_link_header(self):
        import os
        os.environ["ATW_TEST_MENDELEY"] = "tok"
        ws = workspace('[citations]\nprovider = "mendeley"\n[citations.mendeley]\nmode = "api"\ntoken_env = "ATW_TEST_MENDELEY"\n')
        d1 = [{"type": "journal", "title": "A", "year": 2020, "authors": [{"first_name": "Erik", "last_name": "Lindqvist"}],
               "source": "J", "identifiers": {"doi": "10.1/x"}}]
        d2 = [{"type": "book", "title": "B", "year": 2019, "authors": [{"first_name": "S", "last_name": "Brennan"}],
               "citation_key": "Brennan2019"}]
        fake = FakeHTTP([(200, {"link": '<https://api.mendeley.com/documents?marker=2>; rel="next"'}, json.dumps(d1).encode()),
                         (200, {}, json.dumps(d2).encode())])
        meta = library.sync(load_config(ws), fetch=fake)
        self.assertEqual(meta["count"], 2)
        self.assertEqual(fake.calls[0][1]["Authorization"], "Bearer tok")
        items = json.loads((ws / "references.json").read_text())
        self.assertEqual(items[0]["DOI"], "10.1/x")
        self.assertEqual(items[1]["id"], "Brennan2019")

    def test_mendeley_file_ris_and_bibtex(self):
        ws = workspace('[citations]\nprovider = "mendeley"\n[citations.mendeley]\nmode = "file"\nfile = "export.ris"\n')
        (ws / "export.ris").write_text("TY  - JOUR\nAU  - Okafor, Chidi\nTI  - Sensors\nPY  - 2022\nJO  - Letters\nER  - \n")
        meta = library.sync(load_config(ws))
        self.assertEqual(meta["count"], 1)
        self.assertEqual(json.loads((ws / "references.json").read_text())[0]["id"], "Okafor2022")
        (ws / "export.bib").write_text("@article{Tanaka2023, author={Tanaka, Yui}, title={Nodes}, year={2023}}")
        (ws / "thesis.toml").write_text('[citations]\nprovider = "mendeley"\n[citations.mendeley]\nfile = "export.bib"\n')
        library.sync(load_config(ws))
        self.assertEqual(json.loads((ws / "references.json").read_text())[0]["id"], "Tanaka2023")

    def test_no_source(self):
        with self.assertRaises(library.LibraryError):
            library.sync(load_config(workspace("[project]\ntitle='x'\n")))


if __name__ == "__main__":
    unittest.main()
