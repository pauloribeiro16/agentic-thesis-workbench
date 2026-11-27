"""Plugin registry: quality checks, format adapters and citation providers.

Three discovery sources, in this order (later ones may override earlier ids):
1. built-in modules shipped in `atw.builtin`;
2. installed packages exposing the entry-point group `atw.plugins` (standard `importlib.metadata`);
3. local `*.py` files in the workspace's plugin dirs (default `.thesis/plugins/`).

A plugin module declares `PLUGIN = {"id": ..., "version": ..., "api_version": 1}` and a
`register(reg: Registry)` function. A plugin that fails to load or declares another API version is
skipped and reported in `Registry.errors`; it never breaks the others.

Security note: workspace plugins are Python code from the thesis repository and run with your user's
permissions. Only enable plugin dirs you trust.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any, Callable

from .config import WorkbenchConfig

API_VERSION = 1
ENTRY_POINT_GROUP = "atw.plugins"
BUILTIN_MODULES = (
    "atw.builtin.formats",
    "atw.builtin.checks_core",
    "atw.builtin.checks_citations",
    "atw.builtin.checks_style",
    "atw.builtin.checks_pages",
    "atw.builtin.checks_governance",
    "atw.builtin.checks_agent_review",
    "atw.builtin.checks_macro",
)


@dataclass
class CheckSpec:
    id: str
    group: str
    label: str
    rule: str
    func: Callable[..., Any]
    pack: str = "core"
    fail: str = "warn"          # state when findings exist: warn | bad
    scope: str = "chapter"      # chapter | thesis
    source: str = "builtin"

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "group": self.group, "label": self.label, "rule": self.rule,
                "pack": self.pack, "fail": self.fail, "scope": self.scope, "source": self.source}


@dataclass
class Registry:
    checks: dict[str, CheckSpec] = field(default_factory=dict)
    formats: dict[str, Any] = field(default_factory=dict)
    citation_providers: dict[str, Callable[[str], list[dict[str, Any]]]] = field(default_factory=dict)
    plugins: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    _source: str = "builtin"

    def check(self, id: str, *, group: str, label: str, rule: str, pack: str = "core",
              fail: str = "warn", scope: str = "chapter") -> Callable:
        def deco(func: Callable) -> Callable:
            self.checks[id] = CheckSpec(id, group, label, rule, func, pack, fail, scope, self._source)
            return func
        return deco

    def format(self, id: str) -> Callable:
        def deco(cls: Any) -> Any:
            self.formats[id] = cls
            return cls
        return deco

    def citation_provider(self, id: str) -> Callable:
        def deco(func: Callable) -> Callable:
            self.citation_providers[id] = func
            return func
        return deco

    def _register_module(self, mod: Any, source: str) -> None:
        info = dict(getattr(mod, "PLUGIN", {}) or {})
        pid = info.get("id") or getattr(mod, "__name__", source)
        if int(info.get("api_version", API_VERSION)) != API_VERSION:
            self.errors.append(f"{pid}: api_version {info.get('api_version')} != {API_VERSION} (skipped)")
            return
        reg = getattr(mod, "register", None)
        if not callable(reg):
            self.errors.append(f"{pid}: no register(reg) function (skipped)")
            return
        self._source = source
        try:
            reg(self)
            self.plugins.append({"id": pid, "version": str(info.get("version", "0")), "source": source,
                                 "description": str(info.get("description", ""))})
        except Exception as exc:  # a broken plugin must not break the workbench
            self.errors.append(f"{pid}: {type(exc).__name__}: {exc}")
        finally:
            self._source = "builtin"


_BASE: Registry | None = None
_LOCAL_CACHE: dict[tuple, Registry] = {}


def _base_registry() -> Registry:
    global _BASE
    if _BASE is not None:
        return _BASE
    reg = Registry()
    for name in BUILTIN_MODULES:
        try:
            reg._register_module(importlib.import_module(name), "builtin")
        except Exception as exc:
            reg.errors.append(f"{name}: {type(exc).__name__}: {exc}")
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception:
        eps = []
    for ep in eps:
        try:
            obj = ep.load()
            mod = obj if hasattr(obj, "register") else type("EP", (), {"register": staticmethod(obj), "PLUGIN": {"id": ep.name}})
            reg._register_module(mod, f"package:{ep.value}")
        except Exception as exc:
            reg.errors.append(f"{ep.name}: {type(exc).__name__}: {exc}")
    _BASE = reg
    return reg


def _local_files(cfg: WorkbenchConfig) -> list[Path]:
    files: list[Path] = []
    for d in cfg.plugin_dirs:
        root = (cfg.workspace / d).resolve()
        if root.is_dir():
            files.extend(p for p in sorted(root.glob("*.py")) if not p.name.startswith("_"))
    return files


def load_registry(cfg: WorkbenchConfig) -> Registry:
    base = _base_registry()
    files = _local_files(cfg)
    key = (str(cfg.workspace), tuple((str(p), p.stat().st_mtime_ns) for p in files))
    if key in _LOCAL_CACHE:
        return _LOCAL_CACHE[key]
    reg = Registry(dict(base.checks), dict(base.formats), dict(base.citation_providers),
                   list(base.plugins), list(base.errors))
    for p in files:
        name = f"atw_local_{abs(hash(str(p)))}_{p.stem}"
        try:
            spec = importlib.util.spec_from_file_location(name, p)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            reg._register_module(mod, f"workspace:{p.relative_to(cfg.workspace)}")
        except Exception as exc:
            reg.errors.append(f"{p.name}: {type(exc).__name__}: {exc}")
    _LOCAL_CACHE.clear()
    _LOCAL_CACHE[key] = reg
    return reg
