"""Run TLC and read TLA+ values back into Python — the link between a model and the code.

`model_table(module, constants)` makes TLC evaluate the model's `Table` operator and returns it as Python data,
so a conformance test can replay every row on the real code. TLA+ values map to Python as:
sets -> frozenset, sequences/tuples -> tuple, records -> dict, strings -> str, booleans -> bool, integers -> int.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def tlc_available() -> bool:
    return shutil.which("tlc") is not None


def run_tlc(module: str, cfg_text: str, extra_tla: str = "") -> str:
    """Runs TLC on <module>.tla (copied with any extra module text) and returns its output."""
    with tempfile.TemporaryDirectory() as d:
        for f in HERE.glob("*.tla"):
            shutil.copy(f, d)
        name = module
        if extra_tla:
            name = f"{module}Print"
            Path(d, f"{name}.tla").write_text(extra_tla, encoding="utf-8")
        Path(d, f"{name}.cfg").write_text(cfg_text, encoding="utf-8")
        r = subprocess.run(["tlc", "-workers", "1", "-metadir", str(Path(d, "states")), "-config", f"{name}.cfg",
                            f"{name}.tla"], cwd=d, capture_output=True, text=True, timeout=900,
                           env={**os.environ, "JAVA_TOOL_OPTIONS": "-Xss16m"})
        return r.stdout + r.stderr


def model_table(module: str, constants: dict[str, str], operator: str = "Table") -> Any:
    """Evaluates `operator` of `module` with the given constants (TLA+ source text) and parses the value."""
    extra = (f"---- MODULE {module}Print ----\nEXTENDS {module}, TLC\n"
             f"ASSUME PrintT(<<\"ATW_TABLE\", {operator}>>)\n====\n")
    consts = "\n".join(f"  {k} = {v}" for k, v in constants.items())
    cfg = f"CONSTANTS\n{consts}\nSPECIFICATION Spec\nCHECK_DEADLOCK FALSE\n"
    out = run_tlc(module, cfg, extra)
    m = re.search(r'<<\s*"ATW_TABLE"', out)
    start = m.start() if m else -1
    if start < 0:
        raise RuntimeError(f"TLC did not print the table:\n{out[-3000:]}")
    value, _ = parse(_balanced(out, start))
    return value[1]


def _balanced(text: str, start: int) -> str:
    """The printed value that starts at `start`, cut where its brackets close (TLC logs follow it)."""
    depth, i, in_str = 0, start, False
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif text.startswith("<<", i):
            depth += 1
            i += 1
        elif text.startswith(">>", i):
            depth -= 1
            i += 1
            if depth == 0:
                return text[start:i + 1]
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        i += 1
    raise RuntimeError("unbalanced TLA+ value in TLC output")


# --- a small parser for TLC's printed values -------------------------------------------------------------

_TOKEN = re.compile(r'\s*(<<|>>|\|->|[{}\[\],]|"(?:[^"\\]|\\.)*"|TRUE|FALSE|-?\d+|[A-Za-z_][A-Za-z0-9_]*)', re.S)


def _tokens(text: str):
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                return
            raise ValueError(f"cannot read TLA+ value at: {text[pos:pos + 60]!r}")
        yield m.group(1)
        pos = m.end()


def parse(text: str) -> tuple[Any, int]:
    toks = list(_tokens(text))
    val, i = _value(toks, 0)
    return val, i


def _value(t: list[str], i: int) -> tuple[Any, int]:
    tok = t[i]
    if tok == "{":
        items, i = _items(t, i + 1, "}")
        return frozenset(_freeze(x) for x in items), i
    if tok == "<<":
        items, i = _items(t, i + 1, ">>")
        return tuple(items), i
    if tok == "[":
        rec: dict[str, Any] = {}
        i += 1
        while t[i] != "]":
            key = t[i]
            assert t[i + 1] == "|->", f"expected |-> after {key}"
            val, i = _value(t, i + 2)
            rec[key] = val
            if t[i] == ",":
                i += 1
        return rec, i + 1
    if tok.startswith('"'):
        return bytes(tok[1:-1], "utf-8").decode("unicode_escape"), i + 1
    if tok in ("TRUE", "FALSE"):
        return tok == "TRUE", i + 1
    if re.fullmatch(r"-?\d+", tok):
        return int(tok), i + 1
    raise ValueError(f"unexpected token {tok!r}")


def _items(t: list[str], i: int, close: str) -> tuple[list[Any], int]:
    out = []
    while t[i] != close:
        v, i = _value(t, i)
        out.append(v)
        if t[i] == ",":
            i += 1
    return out, i + 1


def _freeze(x: Any) -> Any:
    if isinstance(x, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in x.items()))
    if isinstance(x, tuple):
        return tuple(_freeze(v) for v in x)
    return x


def thaw_record(x: Any) -> Any:
    """Inverse of the freezing used for set members: tuples of (key, value) pairs back to dicts."""
    if isinstance(x, tuple) and x and all(isinstance(p, tuple) and len(p) == 2 and isinstance(p[0], str) for p in x):
        return {k: thaw_record(v) for k, v in x}
    if isinstance(x, tuple):
        return tuple(thaw_record(v) for v in x)
    return x
