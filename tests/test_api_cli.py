"""The HTTP API, the command line, the web client and the non-functional rules, exercised end to end on a copy of
the demo thesis. Each class names the requirements it verifies (REQ: …)."""
import ast
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from atw import __main__ as cli
from atw import server as srv

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "demo-thesis"


def demo_copy() -> Path:
    d = Path(tempfile.mkdtemp()) / "demo"
    shutil.copytree(DEMO, d)
    return d


class LiveServer:
    def __init__(self, ws: Path):
        os.environ["ATW_SIGNING_KEY"] = str(ws / ".thesis" / "demo-signing.key")
        self.app = srv.WorkbenchApp(workspace=ws)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.make_handler(self.app))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def req(self, path, body=None, headers=None, raw=None):
        url = f"http://127.0.0.1:{self.port}/{path.lstrip('/')}"
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        h = {"Content-Type": "application/json"} if data is not None else {}
        h.update(headers or {})
        r = urllib.request.Request(url, data=data, headers=h, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Api(unittest.TestCase):
    """REQ: RF-API-01 RF-API-02 RF-API-03 RNF-SEC-01 RNF-SEC-02 RNF-SEC-03 RNF-SEC-05 RNF-SEC-06"""

    @classmethod
    def setUpClass(cls):
        cls.ws = demo_copy()
        cls.s = LiveServer(cls.ws)

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def test_every_get_endpoint_answers_json(self):  # RF-API-01
        for path in ["api/etag", "api/config", "api/state", "api/summary", "api/literature", "api/quality",
                     "api/quality?chapter=1", "api/queue", "api/agents", "api/output", "api/chapter/1",
                     "api/context/1", "api/work?key=Almeida2021", "api/compile?chapter=1"]:
            code, body = self.s.req(path)
            self.assertEqual(code, 200, (path, body[:200]))
            json.loads(body)
        code, body = self.s.req("/")
        self.assertEqual(code, 200)
        self.assertIn(b"<html", body.lower())

    def test_unknown_and_missing(self):  # RF-API-02
        for path, code in [("api/nope", 404), ("api/chapter/99", 404), ("api/work?key=Nobody", 404)]:
            got, body = self.s.req(path)
            self.assertEqual(got, code, path)
            self.assertIn("error", json.loads(body))
        self.assertEqual(self.s.req("api/nope", {})[0], 404)

    def test_post_endpoints(self):  # RF-API-03
        st = json.loads(self.s.req("api/state")[1])
        th = next(t for t in st["threads"] if t["file"] == "CH3_PLAN.md")
        code, body = self.s.req("api/decide", {"file": "CH3_PLAN.md", "sha": th["sha"],
                                               "decisions": [{"id": "Q3", "state": "APPROVED", "note": "ok"}]})
        self.assertEqual(code, 200, body)
        self.assertEqual(self.s.req("api/decide", {"file": "CH3_PLAN.md", "sha": th["sha"],
                                                   "decisions": [{"id": "Q2", "state": "APPROVED"}]})[0], 409)  # stale sha
        code, body = self.s.req("api/comments", {"ch": 3, "action": "add", "file": "chapters/03_Method.md",
                                                 "quote": "A node whose score falls below 0.5", "kind": "note", "text": "x"})
        self.assertEqual(code, 200, body)
        code, body = self.s.req("api/tasks", {"role": "tone-reviewer", "chapter": 1})
        self.assertEqual(code, 200, body)
        tid = json.loads(body)["tasks"][0]["id"]
        code, body = self.s.req("api/validate", {"task": tid})
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(body)["ok"])  # no output written yet
        self.assertEqual(self.s.req("api/changes", {"action": "decide", "ids": ["P-d4e5f6"], "decision": "rejected"})[0], 200)
        self.assertEqual(self.s.req("api/library", {})[0], 400)          # no reference manager configured
        self.assertEqual(self.s.req("api/template", {"template": "nope"})[0], 400)

    def test_host_must_be_local(self):  # RNF-SEC-01
        for h in ["evil.example", "127.0.0.1.evil.example", "attacker.localhost.com"]:
            self.assertEqual(self.s.req("api/state", headers={"Host": h})[0], 403, h)

    def test_origin_must_be_local(self):  # RNF-SEC-02
        bad = {"Origin": "https://evil.example"}
        self.assertEqual(self.s.req("api/state", headers=bad)[0], 403)
        self.assertEqual(self.s.req("api/comments", {"ch": 1, "action": "add"}, headers=bad)[0], 403)
        self.assertEqual(self.s.req("api/state", headers={"Origin": f"http://127.0.0.1:{self.s.port}"})[0], 200)

    def test_post_rules(self):  # RNF-SEC-03
        self.assertEqual(self.s.req("api/comments", raw=b"{}", headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.s.req("api/comments", raw=b"{not json")[0], 400)
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.s.port, timeout=10)
        c.putrequest("POST", "/api/comments")
        c.putheader("Content-Type", "application/json")
        c.putheader("Content-Length", "2000000")    # refused from the header, before any body is read
        c.endheaders()
        self.assertEqual(c.getresponse().status, 413)
        c.close()

    def test_cross_site_post_is_refused(self):  # RNF-SEC-06
        """A page on any site can POST from a sandboxed iframe (Origin: null) with a CORS-safelisted content type
        (text/plain…) and no preflight. Such a request must never reach an action — or the server would seal an
        approval with the author's key."""
        st = json.loads(self.s.req("api/state")[1])
        th = next(t for t in st["threads"] if t["file"] == "CH3_PLAN.md")
        attack = json.dumps({"file": "CH3_PLAN.md", "sha": th["sha"],
                             "decisions": [{"id": "Q2", "state": "APPROVED"}]}).encode()
        for headers in [{"Origin": "null", "Content-Type": "text/plain; x=application/json"},
                        {"Origin": "null", "Content-Type": "application/json"},
                        {"Content-Type": "text/plain; charset=application/json"}]:
            code, _ = self.s.req("api/decide", raw=attack, headers=headers)
            self.assertIn(code, (403, 415), headers)
        after = json.loads(self.s.req("api/state")[1])
        q2 = next(q for t in after["threads"] if t["file"] == "CH3_PLAN.md" for q in t["questions"] if q["id"] == "Q2")
        self.assertNotEqual(q2["state"], "APPROVED")

    def test_paths_stay_inside_the_thesis(self):  # RNF-SEC-05
        self.assertEqual(self.s.req("api/work/pdf?key=Almeida2021&file=../../../../etc/passwd")[0], 404)
        self.assertEqual(self.s.req("api/decide", {"file": "../../thesis.toml", "decisions": [{"id": "Q1"}]})[0], 400)
        code, body = self.s.req("api/template", {"template": "uminho-phd", "base": "latex"})
        self.assertEqual(code, 200, body)
        from atw import output
        from atw.config import load_config
        ok, msg = output.apply(load_config(self.ws), "uminho-phd", "latex", "../outside")
        self.assertFalse(ok)


class ServerBinding(unittest.TestCase):
    """REQ: RNF-SEC-04 — the server listens on 127.0.0.1 only."""

    def test_binds_loopback(self):
        seen = {}

        class Fake:
            def __init__(self, addr, handler):
                seen["addr"] = addr

            def serve_forever(self):
                raise KeyboardInterrupt

            def server_close(self):
                pass
        orig = srv.ThreadingHTTPServer
        srv.ThreadingHTTPServer = Fake
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                srv.run_server(demo_copy(), port=8799)
        finally:
            srv.ThreadingHTTPServer = orig
        self.assertEqual(seen["addr"], ("127.0.0.1", 8799))


def run_cli(*argv) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 2
    return code, out.getvalue() + err.getvalue()


class Cli(unittest.TestCase):
    """REQ: RF-CLI-01 RF-CLI-02 RF-CLI-03 RF-SEAL-01 RF-SEAL-03 RF-TSK-06"""

    def test_every_command(self):  # RF-CLI-01
        ws = demo_copy()
        os.environ["ATW_SIGNING_KEY"] = str(ws / ".thesis" / "demo-signing.key")
        w = ["--workspace", str(ws)]
        for argv in [["check", "--json"], ["check", "--chapter", "1"], ["task", "list"], ["task", "show", "T-001"],
                     ["task", "new", "--role", "tone-reviewer", "--chapter", "1"], ["review", "validate", "T-001"],
                     ["roles", "list"], ["roles", "show", "implementer"],
                     ["roles", "export", "--to", "markdown", "--dest", "exported"], ["plugins"], ["key", "status"],
                     ["template", "list"], ["template", "status"], ["library", "status"]]:
            code, out = run_cli(*argv, *w)
            self.assertIn(code, (0, 1), (argv, out[-300:]))  # check exits 1 when it finds problems
            self.assertTrue(out.strip(), argv)
        self.assertTrue((ws / "exported").is_dir())

    def test_invalid_input_fails_with_a_message(self):  # RF-CLI-01
        ws = demo_copy()
        w = ["--workspace", str(ws)]
        for argv in [["task", "show", "T-999"], ["review", "validate", "T-999"], ["template", "apply", "--template", "nope"],
                     ["library", "sync"], ["roles", "show", "nobody"]]:
            code, out = run_cli(*argv, *w)
            self.assertNotEqual(code, 0, argv)
            self.assertTrue(out.strip(), argv)

    def test_init_never_overwrites(self):  # RF-CLI-02
        d = Path(tempfile.mkdtemp())
        (d / "thesis.toml").write_text("# mine\n")
        self.assertEqual(run_cli("init", "--workspace", str(d))[0], 0)
        self.assertEqual((d / "thesis.toml").read_text(), "# mine\n")
        self.assertTrue((d / ".thesis" / "plan.toml").is_file())

    def test_vendor(self):  # RF-CLI-03
        d = Path(tempfile.mkdtemp())
        code, out = run_cli("vendor", "--workspace", str(d))
        self.assertEqual(code, 0, out)
        v = d / "agentic-thesis-workbench"
        self.assertTrue((v / "atw" / "templates" / "uminho-phd" / "template.toml").is_file())
        self.assertTrue((v / ".source-commit").is_file())
        self.assertFalse((v / "tests").exists())
        self.assertNotEqual(run_cli("vendor", "--workspace", str(d), "--into", "../elsewhere")[0], 0)

    def test_keys(self):  # RF-SEAL-01 RF-SEAL-03
        d = Path(tempfile.mkdtemp())
        key = d / "k" / "moderator.key"
        (d / "thesis.toml").write_text(f'[agents]\nsign_decisions = true\nkey_path = "{key}"\n')
        os.environ.pop("ATW_SIGNING_KEY", None)
        self.assertEqual(run_cli("key", "status", "--workspace", str(d))[0], 1)     # missing
        self.assertEqual(run_cli("key", "init", "--workspace", str(d))[0], 0)
        first = key.read_bytes()
        self.assertEqual(oct(key.stat().st_mode & 0o777), "0o600")
        self.assertEqual(run_cli("key", "init", "--workspace", str(d))[0], 0)
        self.assertEqual(key.read_bytes(), first)                                   # never replaced
        # without a key the author's approval is refused, never sealed with a new key
        (d / "thesis.toml").write_text('[agents]\nsign_decisions = true\nrequire_key_path = true\ndialogue_dir = "dlg"\n')
        (d / "dlg").mkdir()
        (d / "dlg" / "T.md").write_text("# T\n\n## Turn 1 — A (M) — 2026-01-01\n\n| Q1 | t | OPEN | x | y |\n")
        from atw.config import load_config
        from atw.dialogue import DialogueService, SealKeyMissing
        with self.assertRaises(SealKeyMissing):
            DialogueService(load_config(d)).append_decision("T.md", "", [{"id": "Q1", "state": "APPROVED"}])
        self.assertNotIn("Moderator Decision", (d / "dlg" / "T.md").read_text())

    def test_roles_export_formats(self):  # RF-TSK-06
        ws = demo_copy()
        for fmt in ("claude", "skills", "markdown"):
            code, out = run_cli("roles", "export", "--to", fmt, "--dest", f"x-{fmt}", "--workspace", str(ws))
            self.assertEqual(code, 0, out)
            self.assertTrue(any((ws / f"x-{fmt}").rglob("*.md")), fmt)


class WebClient(unittest.TestCase):
    """REQ: RF-UI-01 RF-UI-02 RF-UI-03"""
    APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_views_exist(self):  # RF-UI-01
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        views = re.search(r"const VIEWS = \[\.\.\.THESIS_TABS, ([^\]]*)\]", self.APP).group(1)
        tabs = re.search(r"const THESIS_TABS = \[([^\]]*)\]", self.APP).group(1)
        for v in re.findall(r'"([a-z]+)"', tabs + views):
            self.assertIn(f'id="view-{v}"', html, v)
            self.assertRegex(self.APP, rf"function render{v.capitalize()}\b|{v}: render", v)

    def test_every_text_exists_in_both_languages(self):  # RF-UI-03
        en = json.loads((ROOT / "web/i18n/en.json").read_text())
        pt = json.loads((ROOT / "web/i18n/pt.json").read_text())
        self.assertEqual(set(en) ^ set(pt), set(), "keys present in only one language")
        used = set(re.findall(r'\bt\("([a-z_]+\.[a-z_.]+)"', self.APP))
        exact = {k for k in used if not k.endswith(("_", "."))}
        prefixes = used - exact                     # t("ms.mode_" + x): some key must start with the prefix
        self.assertEqual(sorted(exact - set(en)), [], "texts used by the app but missing from en.json")
        self.assertEqual(sorted(p for p in prefixes if not any(k.startswith(p) for k in en)), [])

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_question_excerpt(self):  # RF-UI-02
        src = re.search(r"  function qExcerpt\(md, qid\) \{.*?\n  \}\n", self.APP, re.S).group(0)
        js = src + r"""
const md = ["**Q1 — First**", "- **Verdict:** `AGREE`", "- arg one", "", "**Q2 — Second**", "- **Verdict:** `DISAGREE`",
            "", "| Q1 | First | AGENT_CONSENSUS | Jane | x |", "| Q10 | Tenth | OPEN | Jane | y |", "### Part C", "nothing"].join("\n");
const a = qExcerpt(md, "Q1"), b = qExcerpt(md, "Q2"), c = qExcerpt(md, "Q3");
console.log(JSON.stringify({a, b, c}));
"""
        out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
        self.assertIn("arg one", out["a"])
        self.assertIn("AGENT_CONSENSUS", out["a"])
        self.assertNotIn("Q2", out["a"])
        self.assertNotIn("Tenth", out["a"])          # Q10 is not Q1
        self.assertIn("DISAGREE", out["b"])
        self.assertNotIn("arg one", out["b"])
        self.assertEqual(out["c"], "")


class NonFunctional(unittest.TestCase):
    """REQ: RNF-DEP-01 RNF-NET-01"""

    def imports(self):
        for f in (ROOT / "atw").rglob("*.py"):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        yield f, a.name
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    yield f, node.module

    def test_standard_library_only(self):  # RNF-DEP-01
        bad = [(str(f.relative_to(ROOT)), m) for f, m in self.imports()
               if m.split(".")[0] not in sys.stdlib_module_names and m.split(".")[0] != "atw"]
        self.assertEqual(bad, [])

    def test_network_only_in_the_library_connector(self):  # RNF-NET-01
        net = {"urllib.request", "http.client", "socket", "ssl", "ftplib", "smtplib"}
        users = sorted({str(f.relative_to(ROOT)) for f, m in self.imports() if m in net})
        self.assertEqual(users, ["atw/library.py"])


if __name__ == "__main__":
    unittest.main()
