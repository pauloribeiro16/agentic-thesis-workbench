"""Checks that need reading: filled by the latest valid review of the role whose `fills_check` matches."""
from __future__ import annotations

PLUGIN = {"id": "builtin.agent-review", "version": "1.0", "api_version": 1,
          "description": "Narrative coherence, tone and consistency — fed by role reviews, stale when the text changes."}

AGENT_CHECKS = (
    ("narrative", "Narrative coherence", "narrative-reviewer"),
    ("tone", "Tone and register", "tone-reviewer"),
    ("consistency", "Consistency with decisions and glossary", "consistency-checker"),
)


def _make(check_id: str, role: str):
    def fn(ctx, ch):
        from ..formats import get_adapter
        mine = [r for r in ctx.reviews if r["task"].get("chapter") == ch.number
                and (r["task"].get("fills_check") == check_id or r["task"].get("role") == role)]
        if not mine:
            return {"state": "na", "note": f"no review yet — create a '{role}' task"}
        latest = max(mine, key=lambda r: r["mtime"])
        newest_src = max((p.stat().st_mtime for p in get_adapter(ctx.cfg).sources_for(ch.number)), default=0)
        findings = latest["doc"].get("findings") or []
        items = [{"file": f.get("file", ""), "line": f.get("line", 0), "text": f.get("quote", "")[:260],
                  "detail": f"{f.get('severity')}: {f.get('problem', '')}"} for f in findings]
        sev = {f.get("severity") for f in findings}
        state = "bad" if "bad" in sev else "warn" if "warn" in sev else "ok"
        note = f"{latest['task']['id']} by {(latest['doc'].get('agent') or {}).get('name', '?')}"
        if latest["mtime"] < newest_src:
            return {"state": "na", "items": items, "note": note + " — text changed since; review again"}
        return {"state": state, "items": items, "note": note}
    return fn


def register(reg) -> None:
    for cid, label, role in AGENT_CHECKS:
        reg.check(cid, group="Agent review", label=label, rule=f"Latest valid '{role}' review for this chapter",
                  pack="agent-review")(_make(cid, role))
