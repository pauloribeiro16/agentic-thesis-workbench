"""Standalone & Second-Brain dual-mode HTTP server (Python stdlib only)."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .citations import CitationService
from .config import WorkbenchConfig, load_config
from .dialogue import DialogueService
from .formats import FormatAdapter
from .quality import run_quality_checks

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
NEED_STATES = {"AGENT_CONSENSUS", "AGENT_DEADLOCK", "AUTHOR_RESERVED", "SINGLE_PROPOSAL"}


class WorkbenchApp:
    """Stateless-on-disk application state computed live from the thesis workspace."""

    def __init__(self, workspace: str | Path, host_shell: str = "standalone") -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.host_shell = host_shell

    def _cfg(self) -> WorkbenchConfig:
        return load_config(self.workspace)

    def etag(self) -> str:
        cfg = self._cfg()
        h = hashlib.sha256()
        h.update(str(self.workspace).encode("utf-8"))
        for p in [
            self.workspace / "thesis.toml",
            self.workspace / cfg.dialogue_dir,
            self.workspace / cfg.style_guide_file,
        ]:
            if p.exists():
                h.update(str(p.stat().st_mtime_ns).encode("ascii"))
        return h.hexdigest()[:16]

    def state(self) -> dict[str, Any]:
        cfg = self._cfg()
        fmt = FormatAdapter(cfg)
        cit = CitationService(cfg)
        dlg = DialogueService(cfg)

        chapters = fmt.discover_chapters(include_content=False)
        threads = dlg.list_threads()
        entries = cit.load_entries()
        proposals = dlg.load_proposals()
        comments = dlg.load_comments()

        all_questions = [q for t in threads for q in t["questions"]]
        need_count = sum(1 for q in all_questions if q["state"] in NEED_STATES)
        agents = sorted({a for t in threads for a in t["agents"]})

        return {
            "etag": self.etag(),
            "host_shell": self.host_shell,
            "config": cfg.to_public_dict(),
            "stats": {
                "chapters": len(chapters),
                "total_words": sum(c.words for c in chapters),
                "questions_total": len(all_questions),
                "questions_waiting": need_count,
                "literature_total": len(entries),
                "literature_verified": sum(1 for e in entries if e["status"] == "verified"),
                "proposals_count": len(proposals),
                "comments_count": sum(len(v) for v in comments.values()),
                "agents_count": len(agents),
            },
            "chapters": [c.to_dict(include_content=False) for c in chapters],
            "threads": threads,
            "agents": agents,
            "proposals": proposals,
            "comments": comments,
        }

    def chapter_detail(self, num: int) -> dict[str, Any] | None:
        cfg = self._cfg()
        chapters = FormatAdapter(cfg).discover_chapters(include_content=True)
        for c in chapters:
            if c.number == num:
                return c.to_dict(include_content=True)
        return None

    def literature(self) -> dict[str, Any]:
        cfg = self._cfg()
        cit = CitationService(cfg)
        entries = cit.load_entries()
        ledger = cit.load_ledger()
        return {
            "provider": cfg.citation_provider,
            "syntax": cfg.citation_syntax,
            "total": len(entries),
            "verified": sum(1 for e in entries if e["status"] == "verified"),
            "entries": entries,
            "ledger_entries": ledger.get("entries", []),
        }

    def quality(self) -> dict[str, Any]:
        cfg = self._cfg()
        chapters = FormatAdapter(cfg).discover_chapters(include_content=True)
        return run_quality_checks(cfg, chapters, CitationService(cfg))

    def summary(self) -> dict[str, Any]:
        """Compact summary contract compatible with second-brain's Home dashboard."""
        st = self.state()
        return {
            "title": st["config"]["project"]["title"],
            "stats": st["stats"],
            "waiting_questions": [
                q for t in st["threads"] for q in t["questions"] if q["state"] in NEED_STATES
            ][:10],
        }


def make_handler(app: WorkbenchApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            if os.environ.get("ATW_QUIET") != "1":
                super().log_message(fmt, *args)

        def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _send_bytes(self, body: bytes, content_type: str, status: int = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _serve_index(self) -> None:
            html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
            if app.host_shell == "second-brain":
                html = html.replace('href="tokens.css"', 'href="/tokens.css"')
                html = html.replace('src="nav.js"', 'src="/nav.js"')
            self._send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/etag":
                return self._send_json({"etag": app.etag()})
            if path == "/api/config":
                return self._send_json(app._cfg().to_public_dict())
            if path == "/api/state":
                return self._send_json(app.state())
            if path == "/api/summary":
                return self._send_json(app.summary())
            if path == "/api/literature":
                return self._send_json(app.literature())
            if path == "/api/quality":
                return self._send_json(app.quality())
            if path.startswith("/api/chapter/"):
                raw_num = path.rsplit("/", 1)[-1]
                if raw_num.isdigit():
                    ch = app.chapter_detail(int(raw_num))
                    if ch:
                        return self._send_json(ch)
                return self._send_json({"error": "Chapter not found"}, HTTPStatus.NOT_FOUND)

            if path in ("/", "/index.html"):
                return self._serve_index()

            rel = path.lstrip("/")
            target = (WEB_DIR / rel).resolve()
            if WEB_DIR.resolve() in target.parents and target.is_file():
                mime, _ = mimetypes.guess_type(str(target))
                return self._send_bytes(target.read_bytes(), mime or "application/octet-stream")

            return self._serve_index()

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                return self._send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)

            if path in ("/api/decide", "/api/decisions"):
                thread_file = str(body.get("file") or "")
                sha = str(body.get("sha") or "")
                decisions = body.get("decisions") or []
                if not thread_file or not isinstance(decisions, list) or not decisions:
                    return self._send_json({"error": "Missing file or decisions"}, HTTPStatus.BAD_REQUEST)
                ok, msg = DialogueService(app._cfg()).append_decision(thread_file, sha, decisions)
                if not ok:
                    code = HTTPStatus.CONFLICT if "Conflict" in msg else HTTPStatus.BAD_REQUEST
                    return self._send_json({"error": msg}, code)
                return self._send_json({"ok": True, "etag": app.etag()})

            return self._send_json({"error": "Unknown endpoint"}, HTTPStatus.NOT_FOUND)

    return Handler


def run_server(workspace: str | Path, port: int = 8765, host_shell: str = "standalone") -> None:
    app = WorkbenchApp(workspace=workspace, host_shell=host_shell)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    print(f"Agentic Thesis Workbench running at http://127.0.0.1:{port} (mode={host_shell})")
    print(f"Workspace: {app.workspace}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
