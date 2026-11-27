"""Standalone & host-embedded HTTP server (Python stdlib only, 127.0.0.1 only)."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .changes import ChangeService
from .citations import CitationService
from .comments import CommentService
from .config import WorkbenchConfig, load_config
from .dialogue import NEED_STATES, DialogueService, ModeratorSeal
from .formats import get_adapter
from .pages import pdf_path, record_compile, thesis_budgets
from .plugins import load_registry
from .quality import run_quality_checks
from .roles import load_roles, load_workflows
from .tasks import TaskService

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
MAX_BODY = 1_000_000


def _host_ok(value: str) -> bool:
    host = value.strip().lower()
    if host.startswith("["):
        host = host.split("]")[0] + "]"
    else:
        host = host.split(":")[0]
    return host in LOCAL_HOSTS


def text_context(text: str, start: int, end: int, paragraphs: int = 1) -> dict[str, str]:
    """The paragraph(s) around [start, end), plus `paragraphs` neighbours on each side, and the section heading."""
    import re as _re
    a = start
    for _ in range(paragraphs + 1):
        i = text.rfind("\n\n", 0, max(0, a - 1))
        a = 0 if i < 0 else i + 2
    b = end
    for _ in range(paragraphs + 1):
        j = text.find("\n\n", b + 1)
        b = len(text) if j < 0 else j
    heads = [m.group(0).lstrip("# ").strip() for m in _re.finditer(r"(?m)^#{1,6} .+$", text[:start])]
    return {"pre": text[a:start], "post": text[end:b], "section": heads[-1] if heads else ""}


class WorkbenchApp:
    """State is computed live from the thesis workspace on every request (no database)."""

    def __init__(self, workspace: str | Path, host_shell: str = "standalone") -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.host_shell = host_shell
        self.jobs: dict[int, dict[str, Any]] = {}
        self._cache: dict[str, tuple[str, Any]] = {}
        self._jobs_lock = threading.Lock()

    def cfg(self) -> WorkbenchConfig:
        return load_config(self.workspace)

    def etag(self) -> str:
        """Fingerprint of every file the pages depend on (stat only, a few milliseconds)."""
        cfg = self.cfg()
        h = hashlib.sha256(str(self.workspace).encode("utf-8"))
        h.update(json.dumps({k: v.get("running") for k, v in self.jobs.items()}).encode())
        ws = self.workspace
        files = [ws / "thesis.toml", ws / cfg.style_guide_file, ws / cfg.proposals_file, ws / cfg.ledger_file,
                 ws / ".thesis" / "pages.json"]
        for rel in (cfg.plan_file, cfg.bib_file, cfg.csl_file, str(cfg.raw.get("citations", {}).get("integrity_manifest", ""))):
            if rel:
                files.append(ws / rel)
        dirs = [cfg.dialogue_dir, cfg.comments_dir, cfg.tasks_dir, cfg.reviews_dir] + list(cfg.plugin_dirs) + list(cfg.roles_dirs)
        for d in dirs:
            if (ws / d).is_dir():
                files += list((ws / d).iterdir())
        if cfg.library_dir and (ws / cfg.library_dir).is_dir():
            files.append(ws / cfg.library_dir)
        files += get_adapter(cfg).files()
        for tmpl in (cfg.pages_pdf, cfg.pages_aux):
            if tmpl and "{chapter}" in tmpl:
                parent = (ws / tmpl).parent
                if parent.is_dir():
                    files += [f for f in parent.iterdir() if f.suffix in (".pdf", ".aux", ".json")]
        for f in sorted(set(files)):
            try:
                st = f.stat()
                h.update(f"{f}:{st.st_mtime_ns}:{st.st_size}".encode())
            except OSError:
                pass
        return h.hexdigest()[:16]

    def cached(self, key: str, fn) -> Any:
        """Answer from memory while no input changed; recompute when the fingerprint moves."""
        tag = self.etag()
        hit = self._cache.get(key)
        if hit and hit[0] == tag:
            return hit[1]
        value = fn()
        self._cache[key] = (tag, value)
        return value

    def warm(self) -> None:
        """Recompute every page in the background so requests are answered from memory."""
        try:
            self.cached("state", self._state)
            self.cached("queue", self._queue)
            st = self._cache["state"][1]
            for c in st["chapters"]:
                self.cached(f"chapter:{c['number']}", lambda n=c["number"]: self._chapter(n))
            self.cached("quality", lambda: run_quality_checks(self.cfg()))
            self.cached("literature", self._literature)
        except Exception:
            pass

    def start_warmer(self, interval: float = 1.0) -> None:
        def loop() -> None:
            last = ""
            while True:
                try:
                    tag = self.etag()
                    if tag != last:
                        self.warm()
                        last = tag
                except Exception:
                    pass
                time.sleep(interval)
        threading.Thread(target=loop, daemon=True).start()

    def state(self) -> dict[str, Any]:
        return self.cached("state", self._state)

    def _state(self) -> dict[str, Any]:
        cfg = self.cfg()
        adapter = get_adapter(cfg)
        chapters = adapter.discover_chapters(include_content=True)
        threads = DialogueService(cfg).list_threads()
        entries = CitationService(cfg).load_entries()
        queue = self.queue(cfg)
        tasks = TaskService(cfg).list()
        budgets = thesis_budgets(cfg, chapters, adapter)
        ch_dicts = []
        for c in chapters:
            d = c.to_dict(include_content=False)
            d["budget"] = budgets[c.number]
            ch_dicts.append(d)
        qs = [q for t in threads for q in t["questions"]]
        agents = sorted({a for t in threads for a in t["agents"]})
        return {
            "etag": self.etag(),
            "host_shell": self.host_shell,
            "config": cfg.to_public_dict(),
            "signing": ModeratorSeal(cfg).status(),
            "stats": {
                "chapters": len(chapters),
                "total_words": sum(c.words for c in chapters),
                "questions_total": len(qs),
                "questions_waiting": sum(1 for q in qs if q["state"] in NEED_STATES),
                "unauthorised_claims": sum(1 for q in qs if q["unauthorized_claims"]),
                "literature_total": len(entries),
                "literature_verified": sum(1 for e in entries if e["status"] == "verified"),
                "comments_to_close": len(queue["items"]),
                "comments_open": queue["counts"]["open"],
                "comments_approved": queue["counts"]["approved"],
                "changes": queue["changes"],
                "tasks_open": sum(1 for t in tasks if t.get("status") == "open"),
                "agents_count": len(agents),
            },
            "chapters": ch_dicts,
            "threads": threads,
            "agents": agents,
        }

    def summary(self) -> dict[str, Any]:
        """Compact contract for a host portal's home dashboard."""
        st = self.state()
        return {"title": st["config"]["project"]["title"], "stats": st["stats"],
                "waiting_questions": [q for t in st["threads"] for q in t["questions"] if q["state"] in NEED_STATES][:10]}

    def file_chapters(self, cfg: WorkbenchConfig) -> dict[str, int]:
        ws = cfg.workspace
        return {str(p.relative_to(ws)): c.number for c in get_adapter(cfg).discover_chapters()
                for p in get_adapter(cfg).sources_for(c.number)}

    def queue(self, cfg: WorkbenchConfig | None = None) -> dict[str, Any]:
        """Everything waiting for the author to close: comments and change proposals."""
        if cfg is None:
            return self.cached("queue", self._queue)
        return self._queue(cfg)

    def _queue(self, cfg: WorkbenchConfig | None = None) -> dict[str, Any]:
        cfg = cfg or self.cfg()
        q = CommentService(cfg).queue()
        for it in q["items"]:
            it["source"] = "comment"
        cs = ChangeService(cfg)
        changes = cs.load(self.file_chapters(cfg))["items"]
        todo = [dict(i, source="change") for i in changes
                if not i.get("parent") and i["verdict"] in ("pending", "review")]
        texts: dict[str, str] = {}

        def text_of(rel: str) -> str:
            if rel not in texts:
                f = cfg.workspace / rel
                texts[rel] = f.read_text(encoding="utf-8", errors="ignore") if f.is_file() else ""
            return texts[rel]

        for i in todo:
            pos = i["anchor"].get("pos", -1)
            cur = i.get("new", "") if i.get("status") == "applied" else i.get("old", "")
            if pos >= 0:
                i["context"] = text_context(text_of(i["file"]), pos, pos + len(cur))
        for c in q["items"]:
            a = c.get("anchor") or {}
            if a.get("state") in ("exact", "fuzzy"):
                c["context"] = text_context(text_of(c["file"]), a["start"], a["end"])
        todo.sort(key=lambda i: (i["verdict"] != "review", i.get("chapter") or 99, i.get("file", ""), i["anchor"]["pos"]))
        q["items"] = q["items"] + todo
        q["changes"] = cs.counts(changes)
        return q

    def pdf_info(self, cfg: WorkbenchConfig, num: int) -> dict[str, Any]:
        p = pdf_path(cfg, num)
        info: dict[str, Any] = {"exists": bool(p), "can_compile": bool(cfg.compile_command),
                                "job": {k: v for k, v in self.jobs.get(num, {}).items() if k != "thread"}}
        if p:
            info["mtime"] = p.stat().st_mtime
            meta = p.with_suffix(".json")  # optional build report written by the compile command
            if meta.is_file():
                try:
                    info["build"] = json.loads(meta.read_text(encoding="utf-8"))
                except Exception:
                    pass
        return info

    def context(self, num: int) -> dict[str, Any]:
        """Instructions, memories and constraints for one chapter, read from files the thesis lists in [context]."""
        import re as _re
        cfg = self.cfg()
        ad = get_adapter(cfg)
        srcs = ad.sources_for(num)
        ch_dir = str(srcs[0].parent.relative_to(cfg.workspace)) if srcs else ""
        out: list[dict[str, Any]] = []

        def read(rel: str) -> str | None:
            f = (cfg.workspace / rel).resolve()
            if cfg.workspace not in f.parents or not f.is_file():
                return None
            return f.read_text(encoding="utf-8", errors="ignore")

        fill = lambda t: t.format(chapter=num, chapter_dir=ch_dir, dialogue_dir=cfg.dialogue_dir)
        spec = cfg.spec(num)
        if spec:
            lines = [f"- **{k}:** {v}" for k, v in spec.items() if k != "narrative"]
            out.append({"kind": "plan", "title": cfg.plan_file or "plan", "path": cfg.plan_file,
                        "content": (spec.get("narrative", "") + "\n\n" + "\n".join(lines)).strip()})
        for rel in cfg.context_chapter_files:
            rel = fill(rel)
            text = read(rel)
            if text is None:
                continue
            if rel.startswith(cfg.dialogue_dir.rstrip("/") + "/"):
                th = DialogueService(cfg).parse_thread(cfg.workspace / rel)
                qs = th["questions"]
                rows = ["| # | Questão | Estado | Selada |", "|---|---|---|---|"] + [
                    f"| {q['id']} | {q['title'].replace('|', '/')} | {q['state']} | {'sim' if q['authenticated'] else ''} |"
                    for q in qs]
                last = th["turns"][-3:]
                text = (f"{len(qs)} questões, {sum(1 for q in qs if q['needs_author'])} à espera do autor.\n\n" + "\n".join(rows)
                        + "\n\n" + "\n\n".join(f"### {t['heading']}\n\n{t['md'][:1500]}" for t in reversed(last)))
            out.append({"kind": "chapter", "title": Path(rel).name, "path": rel, "content": text})
        pats = [rf"\bCap(?:ítulo|\.)?\s*{num}\b", rf"\bChapter\s+{num}\b", rf"\bCH{num}\b", rf"\bCaps?\.\s*(?:\d+\s*(?:,|e|a|–|-)\s*)*{num}\b"]
        for rel in cfg.context_memory_files:
            text = read(fill(rel))
            if not text:
                continue
            blocks = _re.split(r"(?m)^(?=## )", text)
            hits = [b.strip() for b in blocks if b.startswith("## ") and any(_re.search(p, b, _re.I) for p in pats)]
            if hits:
                out.append({"kind": "memory", "title": Path(rel).name, "path": fill(rel), "content": "\n\n".join(hits[::-1])})
        for rel in cfg.context_thesis_files:
            text = read(fill(rel))
            if text is not None:
                out.append({"kind": "thesis", "title": Path(rel).name, "path": fill(rel), "content": text})
        return {"chapter": num, "docs": out}

    def chapter(self, num: int) -> dict[str, Any] | None:
        return self.cached(f"chapter:{num}", lambda: self._chapter(num))

    def _chapter(self, num: int) -> dict[str, Any] | None:
        cfg = self.cfg()
        adapter = get_adapter(cfg)
        all_ch = adapter.discover_chapters(include_content=True)
        budgets = thesis_budgets(cfg, all_ch, adapter)
        for c in all_ch:
            if c.number == num:
                d = c.to_dict(include_content=True)
                d["comments"] = CommentService(cfg).with_anchors(num)
                files = {s.rel_path for s in c.sections}
                d["changes"] = [i for i in ChangeService(cfg).load()["items"] if i.get("file") in files]
                d["budget"] = budgets[num]
                d["pdf"] = self.pdf_info(cfg, num)
                return d
        return None

    def literature(self) -> dict[str, Any]:
        return self.cached("literature", self._literature)

    def _literature(self) -> dict[str, Any]:
        cfg = self.cfg()
        svc = CitationService(cfg)
        entries = svc.load_entries()
        from .citations import enrich_works
        summary = enrich_works(cfg, entries)
        return {"provider": cfg.citation_provider, "syntax": cfg.citation_syntax, "total": len(entries),
                "verified": summary["passages"], "summary": summary, "entries": entries}

    def agents(self) -> dict[str, Any]:
        cfg = self.cfg()
        roles, role_errors = load_roles(cfg)
        reg = load_registry(cfg)
        ts = TaskService(cfg)
        return {"roles": [r.public() for r in roles.values()], "role_errors": role_errors,
                "workflows": list(load_workflows(cfg).values()), "tasks": ts.list(),
                "reviews": [{"task": r["task"]["id"], "role": r["task"].get("role"), "chapter": r["task"].get("chapter"),
                             "valid": r["valid"], "summary": r["doc"].get("summary", ""),
                             "agent": r["doc"].get("agent"), "findings": r["doc"].get("findings", [])}
                            for r in ts.reviews()],
                "plugins": reg.plugins, "plugin_errors": reg.errors,
                "checks": [s.public() for s in reg.checks.values()]}

    def compile(self, chapter: int) -> dict[str, Any]:
        """Start the configured compile command in the background; poll with GET api/compile?chapter=N."""
        cfg = self.cfg()
        if not cfg.compile_command:
            return {"ok": False, "error": "no [format] compile_command in thesis.toml"}
        with self._jobs_lock:
            job = self.jobs.get(chapter)
            if job and job.get("running"):
                return {"ok": True, "running": True}
            job = {"running": True, "started": time.time(), "finished": None, "ok": None, "log": ""}
            self.jobs[chapter] = job

        def run() -> None:
            cmd = [part.replace("{chapter}", str(chapter)) for part in cfg.compile_command]
            try:
                p = subprocess.run(cmd, cwd=self.workspace, capture_output=True, text=True, timeout=900)
                job.update(ok=p.returncode == 0, code=p.returncode, log=(p.stdout + p.stderr)[-4000:])
            except Exception as exc:
                job.update(ok=False, log=f"{type(exc).__name__}: {exc}")
            if job["ok"]:
                try:
                    c2 = self.cfg()
                    ad = get_adapter(c2)
                    ch = next((c for c in ad.discover_chapters() if c.number == chapter), None)
                    from .pages import compiled_pages
                    pages = compiled_pages(c2, chapter, ad.sources_for(chapter))["pages"]
                    if ch:
                        record_compile(c2, chapter, ch.words, pages)
                except Exception:
                    pass
            job.update(running=False, finished=time.time())

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True, "running": True}


def make_handler(app: WorkbenchApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            if os.environ.get("ATW_QUIET") != "1":
                super().log_message(fmt, *args)

        def _send(self, body: bytes, ctype: str, status: int = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
            self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

        def _guard(self) -> bool:
            """Only requests addressed to this machine (blocks DNS rebinding); with an Origin, only from this machine."""
            if not _host_ok(self.headers.get("Host", "")):
                self._json({"error": "forbidden host"}, HTTPStatus.FORBIDDEN)
                return False
            origin = self.headers.get("Origin")
            if origin and origin != "null" and not _host_ok(urlparse(origin).netloc):
                self._json({"error": "forbidden origin"}, HTTPStatus.FORBIDDEN)
                return False
            return True

        def _index(self) -> None:
            html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
            if app.host_shell == "second-brain":
                html = html.replace('href="tokens.css"', 'href="/tokens.css"').replace('src="nav.js"', 'src="/nav.js"')
            self._send(html.encode("utf-8"), "text/html; charset=utf-8")

        def do_GET(self) -> None:
            if not self._guard():
                return
            url = urlparse(self.path)
            path, qs = url.path, parse_qs(url.query)
            try:
                if path == "/api/etag":
                    return self._json({"etag": app.etag()})
                if path == "/api/config":
                    return self._json(app.cfg().to_public_dict())
                if path == "/api/state":
                    return self._json(app.state())
                if path == "/api/summary":
                    return self._json(app.summary())
                if path == "/api/literature":
                    return self._json(app.literature())
                if path == "/api/quality":
                    ch = qs.get("chapter", [""])[0]
                    if ch.isdigit():
                        return self._json(run_quality_checks(app.cfg(), only_chapter=int(ch)))
                    return self._json(app.cached("quality", lambda: run_quality_checks(app.cfg())))
                if path == "/api/queue":
                    return self._json(app.queue())
                if path == "/api/compile":
                    ch = qs.get("chapter", [""])[0]
                    return self._json(app.pdf_info(app.cfg(), int(ch)) if ch.isdigit() else {"error": "chapter?"})
                if path.startswith("/api/pdf/"):
                    raw = path.rsplit("/", 1)[-1]
                    pdf = pdf_path(app.cfg(), int(raw)) if raw.isdigit() else None
                    if not pdf:
                        return self._json({"error": "no PDF yet — compile the chapter"}, HTTPStatus.NOT_FOUND)
                    return self._send(pdf.read_bytes(), "application/pdf")
                if path == "/api/agents":
                    return self._json(app.agents())
                if path.startswith("/api/context/"):
                    raw = path.rsplit("/", 1)[-1]
                    return self._json(app.context(int(raw))) if raw.isdigit() else self._json({"error": "chapter?"}, HTTPStatus.BAD_REQUEST)
                if path.startswith("/api/chapter/"):
                    raw = path.rsplit("/", 1)[-1]
                    ch = app.chapter(int(raw)) if raw.isdigit() else None
                    return self._json(ch) if ch else self._json({"error": "chapter not found"}, HTTPStatus.NOT_FOUND)
                if path.startswith("/api/"):
                    return self._json({"error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)
            except Exception as exc:
                return self._json({"error": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            if path in ("/", "/index.html"):
                return self._index()
            target = (WEB_DIR / path.lstrip("/")).resolve()
            if WEB_DIR.resolve() in target.parents and target.is_file():
                mime, _ = mimetypes.guess_type(str(target))
                return self._send(target.read_bytes(), mime or "application/octet-stream")
            return self._index()

        def do_POST(self) -> None:
            if not self._guard():
                return
            path = urlparse(self.path).path
            if "application/json" not in self.headers.get("Content-Type", ""):
                return self._json({"error": "Content-Type must be application/json"}, HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length > MAX_BODY:
                return self._json({"error": "request too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")
            except Exception:
                return self._json({"error": "invalid JSON"}, HTTPStatus.BAD_REQUEST)
            cfg = app.cfg()
            try:
                if path == "/api/decide":
                    decisions = body.get("decisions") or []
                    if not body.get("file") or not isinstance(decisions, list) or not decisions:
                        return self._json({"error": "missing file or decisions"}, HTTPStatus.BAD_REQUEST)
                    ok, msg = DialogueService(cfg).append_decision(str(body["file"]), str(body.get("sha") or ""), decisions)
                    if not ok:
                        return self._json({"error": msg}, HTTPStatus.CONFLICT if "Conflict" in msg else HTTPStatus.BAD_REQUEST)
                    return self._json({"ok": True, "etag": app.etag()})
                if path == "/api/comments":
                    code, out = CommentService(cfg).apply(body)
                    return self._json(out, code)
                if path == "/api/changes":
                    code, out = ChangeService(cfg).apply(body)
                    return self._json(out, code)
                if path == "/api/tasks":
                    ch = body.get("chapter")
                    created = TaskService(cfg).create(role=body.get("role"), workflow=body.get("workflow"),
                                                      chapter=int(ch) if ch not in (None, "") else None,
                                                      comment_ids=body.get("comment_ids"), note=str(body.get("note") or ""))
                    return self._json({"ok": True, "tasks": created})
                if path == "/api/validate":
                    ok, errors = TaskService(cfg).validate(str(body.get("task") or ""))
                    return self._json({"ok": ok, "errors": errors})
                if path == "/api/compile":
                    return self._json(app.compile(int(body.get("chapter") or 0)))
            except ValueError as exc:
                return self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return self._json({"error": "unknown endpoint"}, HTTPStatus.NOT_FOUND)

    return Handler


def run_server(workspace: str | Path, port: int = 8765, host_shell: str = "standalone") -> None:
    app = WorkbenchApp(workspace=workspace, host_shell=host_shell)
    app.start_warmer()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    print(f"Agentic Thesis Workbench at http://127.0.0.1:{port} (mode={host_shell})\nWorkspace: {app.workspace}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
