"""Governance checks across the whole thesis: decisions, unauthorised claims, comments to close, tasks."""
from __future__ import annotations

PLUGIN = {"id": "builtin.governance", "version": "1.0", "api_version": 1,
          "description": "Pending decisions, unauthorised approvals, comments waiting to be closed, invalid agent outputs."}


def register(reg) -> None:
    register_changes(reg)

    @reg.check("dec_pending", group="Decisions", label="Decisions waiting for the author",
               rule="Questions in consensus, deadlock, reserved or single proposal", pack="governance", scope="thesis")
    def dec_pending(ctx):
        return [{"file": q["thread"], "line": 0, "text": q["title"], "detail": f"{q['id']} · {q['state']}"}
                for q in ctx.questions if q.get("needs_author")]

    @reg.check("dec_unauthorised", group="Decisions", label="Unauthorised approvals",
               rule="Approvals written by an agent, or decision blocks without a valid seal, never count",
               pack="governance", scope="thesis", fail="bad")
    def dec_unauthorised(ctx):
        out = []
        for q in ctx.questions:
            claims = q.get("unauthorized_claims", [])
            if claims:
                who = sorted({c["agent"] or "?" for c in claims})
                kinds = sorted({c["source"] for c in claims})
                out.append({"file": q["thread"], "line": 0, "text": q["title"],
                            "detail": f"{q['id']}: {len(claims)}× by {', '.join(who)} ({', '.join(kinds)})"})
        note = "" if ctx.cfg.key_path or not ctx.cfg.sign_decisions else \
            "no signing key configured: sealed decisions cannot be verified ([agents] key_path)"
        return {"items": out, "note": note} if out else []

    @reg.check("comments_to_close", group="Decisions", label="Comments waiting to be closed",
               rule="Agent answers to accept, and applied changes to confirm", pack="governance", scope="thesis")
    def comments_to_close(ctx):
        from ..comments import CommentService
        q = CommentService(ctx.cfg).queue()
        return [{"file": c.get("file", ""), "line": 0, "text": c.get("quote", "")[:200], "detail": f"{c['id']} · {c['status']}"}
                for c in q["items"]]

    @reg.check("comments_orphan", group="Decisions", label="Comments that lost their place",
               rule="The commented text changed too much; re-attach or close them", pack="governance", scope="thesis")
    def comments_orphan(ctx):
        from ..comments import CommentService
        cs = CommentService(ctx.cfg)
        return [{"file": c.get("file", ""), "line": 0, "text": c.get("quote", "")[:200], "detail": c["id"]}
                for ch in cs.chapters_with_comments() for c in cs.with_anchors(ch)
                if c["anchor"]["state"] == "orphan" and c["status"] not in ("resolved", "wontfix")]

    @reg.check("tasks_invalid", group="Decisions", label="Agent outputs that failed validation",
               rule="Run `atw review validate <TASK>` and fix the reported errors", pack="governance", scope="thesis")
    def tasks_invalid(ctx):
        from ..tasks import TaskService
        return [{"file": t["output"], "line": 0, "text": "; ".join(t.get("errors", []))[:240], "detail": t["id"]}
                for t in TaskService(ctx.cfg).list() if t.get("status") == "invalid"]


def _changes(ctx):
    from ..changes import ChangeService
    return [i for i in ChangeService(ctx.cfg).load()["items"] if not i.get("parent")]


def _citem(i):
    return {"file": i.get("file", ""), "line": 0, "text": (i.get("desc") or i.get("old") or "")[:200],
            "detail": f"{i['id']}{' · ' + i['q'] if i.get('q') else ''}"}


def register_changes(reg) -> None:
    @reg.check("changes_pending", group="Decisions", label="Changes waiting for a decision",
               rule="Proposed edits not yet approved or rejected", pack="governance", scope="thesis")
    def changes_pending(ctx):
        return [_citem(i) for i in _changes(ctx) if i["verdict"] == "pending"]

    @reg.check("changes_review", group="Decisions", label="Changes in the text without your approval",
               rule="Applied edits you have not kept or contested", pack="governance", scope="thesis")
    def changes_review(ctx):
        return [_citem(i) for i in _changes(ctx) if i["verdict"] == "review"]

    @reg.check("changes_register", group="Decisions", label="Decisions not yet registered",
               rule="Approved or rejected changes not yet recorded in their dialogue thread", pack="governance",
               scope="thesis")
    def changes_register(ctx):
        return [_citem(i) for i in _changes(ctx) if i["verdict"] in ("approved", "rejected") and not i.get("registered")]

    @reg.check("changes_lost", group="Decisions", label="Pending changes whose text is gone",
               rule="The text a pending change replaces is no longer in the file", pack="governance", scope="thesis")
    def changes_lost(ctx):
        return [_citem(i) for i in _changes(ctx) if i["verdict"] == "pending" and i["anchor"]["state"] == "missing"]
