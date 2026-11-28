"""Traceability: requirements -> verifications. Checks every link and writes docs/REQUIREMENTS.md.

    python3 verify/trace.py           # check the links and (re)write docs/REQUIREMENTS.md
    python3 verify/trace.py --check   # exit 1 if a link is broken, a requirement is unverified or the doc is stale

Requirements come from verify/requirements.toml plus one RF-QL-<id> per registered quality check (from the plugin
registry, so a new check is a new requirement). Links:
  tla:<Module>.tla#<Operator>@<config>.cfg   the operator is defined in the module and listed under INVARIANTS or
                                             PROPERTIES of that config (TLC proves it in verify/run.sh)
  test:<file>::<Class>::<method>             the test exists (read with ast, not imported)
"""
from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VERIFY = ROOT / "verify"
DOC = ROOT / "docs" / "REQUIREMENTS.md"
CHECKS_TEST = "tests/test_checks_each.py"


def check_requirements() -> list[dict[str, Any]]:
    sys.path.insert(0, str(ROOT))
    from atw.config import load_config
    from atw.plugins import load_registry
    reg = load_registry(load_config(ROOT / "examples" / "demo-thesis"))
    out = []
    for cid, meta in sorted(reg.checks.items()):
        m = meta if isinstance(meta, dict) else {}
        out.append({"id": f"RF-QL-{cid}", "area": f"Quality — {m.get('group', 'checks')}",
                    "text": f"Check '{cid}' ({m.get('label', cid)}): {m.get('rule', '')}. It reports a text that "
                            f"breaks the rule ({m.get('fail', 'warn')}) and accepts a clean one.",
                    "source": f"plugin {m.get('source', 'builtin')} · pack {m.get('pack', '')} · scope {m.get('scope', '')}",
                    "verified_by": [f"test:{CHECKS_TEST}::Checks::test_{cid}"], "generated": True})
    return out


def load() -> list[dict[str, Any]]:
    data = tomllib.loads((VERIFY / "requirements.toml").read_text(encoding="utf-8"))
    return list(data.get("req", [])) + check_requirements()


_TESTS: dict[str, set[str]] = {}


def _test_names(rel: str) -> set[str]:
    if rel not in _TESTS:
        p = ROOT / rel
        names: set[str] = set()
        if p.is_file():
            for node in ast.parse(p.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.ClassDef):
                    for f in node.body:
                        if isinstance(f, ast.FunctionDef) and f.name.startswith("test"):
                            names.add(f"{node.name}::{f.name}")
        _TESTS[rel] = names
    return _TESTS[rel]


def resolve(link: str) -> str | None:
    """None when the link resolves, otherwise why it does not."""
    kind, _, rest = link.partition(":")
    if kind == "test":
        rel, _, name = rest.partition("::")
        if not (ROOT / rel).is_file():
            return f"no file {rel}"
        return None if name in _test_names(rel) else f"no test {name} in {rel}"
    if kind == "tla":
        m = re.fullmatch(r"([A-Za-z]+\.tla)#([A-Za-z]+)@([A-Za-z_]+\.cfg)", rest)
        if not m:
            return "malformed tla link"
        module, op, cfg = m.groups()
        mp, cp = VERIFY / module, VERIFY / cfg
        if not mp.is_file() or not cp.is_file():
            return f"missing {module} or {cfg}"
        if not re.search(rf"^{op}\s*==", mp.read_text(encoding="utf-8"), re.M):
            return f"{op} not defined in {module}"
        listed = re.findall(r"^(?:INVARIANTS?|PROPERTIES|PROPERTY)\s+(.*)$", cp.read_text(encoding="utf-8"), re.M)
        if op not in " ".join(listed).split():
            return f"{op} not checked by {cfg}"
        return None
    return f"unknown link kind {kind!r}"


def method(link: str) -> str:
    if link.startswith("tla:"):
        return "TLA+ (TLC)"
    if "test_conformance_" in link:
        return "conformance"
    if "test_properties" in link:
        return "property"
    return "test"


def problems(reqs: list[dict[str, Any]]) -> list[str]:
    out, seen = [], set()
    for r in reqs:
        if r["id"] in seen:
            out.append(f"{r['id']}: duplicate id")
        seen.add(r["id"])
        if not r.get("verified_by"):
            out.append(f"{r['id']}: no verification")
        for link in r.get("verified_by", []):
            why = resolve(link)
            if why:
                out.append(f"{r['id']}: {link} — {why}")
    # every REQ id named in a test docstring/comment must exist
    ids = {r["id"] for r in reqs}
    for f in sorted((ROOT / "tests").glob("test_*.py")):
        for rid in set(re.findall(r"\bR(?:F|NF)-[A-Z]+-[0-9A-Za-z_]+\b", f.read_text(encoding="utf-8"))):
            if rid not in ids and not rid.startswith("RF-QL-"):
                out.append(f"{f.name} names {rid}, which is not a requirement")
    return out


def render(reqs: list[dict[str, Any]]) -> str:
    def link_md(link: str) -> str:
        if link.startswith("tla:"):
            module, op, cfg = re.fullmatch(r"tla:([^#]+)#([^@]+)@(.+)", link).groups()
            return f"[`{op}`](../verify/{module}) · `{cfg}`"
        rel, _, name = link[5:].partition("::")
        return f"[`{name.split('::')[-1]}`](../{rel})"

    counts: dict[str, int] = {}
    formal = 0
    for r in reqs:
        ms = {method(l) for l in r["verified_by"]}
        formal += "TLA+ (TLC)" in ms
        for m in ms:
            counts[m] = counts.get(m, 0) + 1
    lines = [
        "# Requirements and their verification",
        "",
        "> Generated by `python3 verify/trace.py` from `verify/requirements.toml` and the check registry — do not edit.",
        "> `verify/run.sh` runs TLC on every model, then all tests; `tests/test_traceability.py` fails if any",
        "> requirement is unverified, any link is broken or this file is stale.",
        "",
        f"**{len(reqs)} requirements**, every one with at least one verification. "
        f"{formal} are proved on a TLA+ model by TLC and linked to the code by conformance tests that replay every "
        "row of the model's table on the real implementation; the rest are verified by property tests (many "
        "generated inputs) and example tests.",
        "",
        "| Method | Requirements |",
        "|---|---|",
    ] + [f"| {m} | {n} |" for m, n in sorted(counts.items(), key=lambda x: -x[1])] + [
        "",
        "Methods: **TLA+ (TLC)** — an invariant or temporal property checked over every reachable state of the model; "
        "**conformance** — every sequence in the model's table (thousands) replayed on the real code, results equal; "
        "**property** — a law checked on hundreds of generated inputs; **test** — an example test.",
        "",
        "See [verify/README.md](../verify/README.md) for the models, what each proves and the defects the "
        "verification found.",
        "",
    ]
    areas: dict[str, list[dict[str, Any]]] = {}
    for r in reqs:
        areas.setdefault(r["area"], []).append(r)
    for area, rs in areas.items():
        lines += [f"## {area}", "", "| Id | Requirement | Implemented in | Verified by |", "|---|---|---|---|"]
        for r in rs:
            text = r["text"].replace("|", "\\|")
            lines.append(f"| `{r['id']}` | {text} | {r['source'].replace('|', '/')} | "
                         + "<br>".join(f"{method(l)}: {link_md(l)}" for l in r["verified_by"]) + " |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    reqs = load()
    bad = problems(reqs)
    for b in bad:
        print("BROKEN", b)
    doc = render(reqs)
    if "--check" in argv:
        stale = not DOC.is_file() or DOC.read_text(encoding="utf-8") != doc
        if stale:
            print("STALE docs/REQUIREMENTS.md — run python3 verify/trace.py")
        print(f"{len(reqs)} requirements · {len(bad)} problems")
        return 1 if bad or stale else 0
    DOC.write_text(doc, encoding="utf-8")
    print(f"{len(reqs)} requirements · {len(bad)} problems · wrote {DOC.relative_to(ROOT)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
