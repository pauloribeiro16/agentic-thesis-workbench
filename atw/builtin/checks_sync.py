"""Generated files stay in sync with the manuscript (e.g. the LaTeX produced from Markdown)."""
from __future__ import annotations

import subprocess

PLUGIN = {"id": "builtin.sync", "version": "1.0", "api_version": 1,
          "description": "A generated file (e.g. chapter .tex) equals what its generator produces from the manuscript today."}


def register(reg) -> None:
    @reg.check("generated_sync", group="Structure", label="Generated file matches the manuscript",
               rule="[format.sync] command prints the generated text; it must equal [format.sync] target", fail="bad")
    def generated_sync(ctx, ch):
        sync = ctx.cfg.raw.get("format", {}).get("sync") or {}
        cmd, target = sync.get("command"), sync.get("target")
        if not cmd or not target:
            return {"state": "ok", "note": "not configured"}
        argv = [str(x).replace("{chapter}", str(ch.number)) for x in cmd]
        tpath = ctx.cfg.workspace / str(target).format(chapter=ch.number)
        try:
            p = subprocess.run(argv, cwd=ctx.cfg.workspace, capture_output=True, text=True, timeout=60)
        except Exception as exc:
            return {"state": "error", "note": f"{type(exc).__name__}: {exc}"}
        if p.returncode != 0:
            return {"state": "warn", "note": f"no generator for chapter {ch.number} (exit {p.returncode})"}
        have = tpath.read_text(encoding="utf-8", errors="replace") if tpath.is_file() else None
        if have is None:
            return {"state": "warn", "note": f"{tpath.relative_to(ctx.cfg.workspace)} does not exist yet"}
        if have.rstrip("\n") == p.stdout.rstrip("\n"):
            return {"state": "ok", "note": "identical to the generated text"}
        return {"state": "bad", "count": 1, "note": "the stored file is behind the manuscript — regenerate it",
                "items": [{"file": str(tpath.relative_to(ctx.cfg.workspace)), "line": 0,
                           "text": "differs from what the generator produces today", "detail": " ".join(argv)}]}
