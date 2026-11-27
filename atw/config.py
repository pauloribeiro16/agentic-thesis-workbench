"""Configuration loader for Agentic Thesis Workbench.

Two kinds of settings, kept apart on purpose:

* **Wiring** — `thesis.toml`: where the chapters, bibliography, dialogue and comments live and how to read them.
* **The author's plan** — a separate file named by `[project] plan` (e.g. `.thesis/plan.toml`): how many
  chapters, the pages, words and sections each one should have, what each chapter must argue (narrative) and
  the writing rules. These are one author's choices, never engine defaults.

The engine ships with neutral defaults: no page or word targets, no sentence limit and no word lists. A check
whose rule the author did not set reports "not configured" instead of inventing a limit.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_EXCLUDE = [".git", ".thesis", "node_modules", "__pycache__"]
DEFAULT_PACKS = ["core", "citations", "style", "governance", "agent-review", "thesis-level"]


@dataclass
class WorkbenchConfig:
    workspace: Path
    title: str = "Untitled Thesis"
    author: str = "Author"
    language: str = "en-US"

    # Interface (UI strings only; data, files and code stay in English)
    ui_locale: str = "en"

    # Format adapter
    format_adapter: str = "markdown"
    chapters_glob: str = "chapters/*.md"
    exclude_dirs: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    exclude_files: list[str] = field(default_factory=lambda: ["README.md"])
    compiler: str = "none"
    compile_command: list[str] = field(default_factory=list)  # placeholders: {chapter}
    word_targets: dict[int, tuple[int, int]] = field(default_factory=dict)
    default_word_target: tuple[int, int] | None = None
    expected_sections: int | None = None
    sections_by_chapter: dict[int, int] = field(default_factory=dict)
    page_limit: int | None = None
    page_targets: dict[int, tuple[int, int]] = field(default_factory=dict)  # [min, max] pages per chapter
    pages_pdf: str = ""        # e.g. "build/ch{chapter}.pdf"
    pages_aux: str = ""        # optional LaTeX .aux; with pages_aux_label counts pages up to a label
    pages_aux_label: str = ""

    # Citations adapter
    citation_provider: str = "bibtex"
    bib_file: str = ""
    csl_file: str = ""
    library_dir: str = ""
    citation_syntax: str = "author-year"
    citation_aliases: dict[str, str] = field(default_factory=dict)
    ledger_file: str = ".thesis/citations/ledger.json"

    # Agents & governance
    dialogue_dir: str = ".thesis/dialogue"
    dialogue_profile: str = "en"  # en | pt-legacy
    proposals_file: str = ".thesis/proposals/proposals.json"
    comments_dir: str = ".thesis/comments"
    tasks_dir: str = ".thesis/tasks"
    reviews_dir: str = ".thesis/reviews"
    roles_dirs: list[str] = field(default_factory=lambda: [".thesis/roles"])
    style_guide_file: str = ".thesis/style/guide.json"
    moderator_name: str = "Author"
    sign_decisions: bool = True
    key_path: str = ""
    require_key_path: bool = False   # true: never fall back to the default key location

    # Plugins & quality
    plugin_dirs: list[str] = field(default_factory=lambda: [".thesis/plugins"])
    quality_packs: list[str] = field(default_factory=lambda: list(DEFAULT_PACKS))
    disabled_checks: list[str] = field(default_factory=list)
    max_sentence_words: int | None = None
    forbid_first_person: bool = False
    spelling_variant: str = "none"  # none | en-GB | en-US
    prohibited_phrases: list[str] = field(default_factory=list)
    emphasis_words: list[str] = field(default_factory=list)
    quality_options: dict[str, Any] = field(default_factory=dict)  # [quality.options] for plugins
    # Context shown with each chapter (instructions, memories, constraints). Placeholders: {chapter}, {chapter_dir},
    # {dialogue_dir}. memory_files are searched for entries ("## ..." blocks) that mention the chapter.
    context_chapter_files: list[str] = field(default_factory=list)
    context_thesis_files: list[str] = field(default_factory=list)
    context_memory_files: list[str] = field(default_factory=list)

    # The author's plan
    plan_file: str = ""
    plan: dict[str, Any] = field(default_factory=dict)              # raw plan file, to show what is "yours"
    chapter_specs: dict[int, dict[str, Any]] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def path(self, rel: str) -> Path:
        return self.workspace / rel

    def word_target(self, chapter: int) -> tuple[int, int] | None:
        return self.word_targets.get(chapter, self.default_word_target)

    def sections_for(self, chapter: int) -> int | None:
        return self.sections_by_chapter.get(chapter, self.expected_sections)

    def spec(self, chapter: int) -> dict[str, Any]:
        return self.chapter_specs.get(chapter, {})

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "workspace": str(self.workspace),
            "project": {"title": self.title, "author": self.author, "language": self.language},
            "ui": {"locale": self.ui_locale},
            "plan": {"file": self.plan_file, "chapters": {str(k): v for k, v in sorted(self.chapter_specs.items())},
                     "keys": sorted(self.plan.keys())},
            "format": {
                "adapter": self.format_adapter,
                "chapters_glob": self.chapters_glob,
                "compiler": self.compiler,
                "can_compile": bool(self.compile_command),
                "default_word_target": list(self.default_word_target),
                "expected_sections": self.expected_sections,
                "page_limit": self.page_limit,
                "has_pdf": bool(self.pages_pdf),
            },
            "citations": {
                "provider": self.citation_provider,
                "bib_file": self.bib_file,
                "csl_file": self.csl_file,
                "library_dir": self.library_dir,
                "syntax": self.citation_syntax,
                "ledger_file": self.ledger_file,
            },
            "agents": {
                "dialogue_dir": self.dialogue_dir,
                "dialogue_profile": self.dialogue_profile,
                "moderator_name": self.moderator_name,
                "sign_decisions": self.sign_decisions,
                "tasks_dir": self.tasks_dir,
                "reviews_dir": self.reviews_dir,
            },
            "quality": {
                "packs": self.quality_packs,
                "disabled_checks": self.disabled_checks,
                "max_sentence_words": self.max_sentence_words,
                "forbid_first_person": self.forbid_first_person,
                "spelling_variant": self.spelling_variant,
            },
        }


def _auto_detect(workspace: Path) -> dict[str, Any]:
    """Infer generic defaults when a workspace has no thesis.toml yet."""
    detected: dict[str, Any] = {}
    bibs = sorted(workspace.glob("*.bib"))
    if bibs:
        detected["bib_file"] = bibs[0].name
    for c in sorted(workspace.glob("*.json")):
        if "csl" in c.name.lower() or "references" in c.name.lower():
            detected["csl_file"] = c.name
            if not bibs:
                detected["citation_provider"] = "csl-json"
            break
    ch = workspace / "chapters"
    if ch.is_dir() and list(ch.glob("*.tex")) and not list(ch.glob("*.md")):
        detected["format_adapter"] = "latex"
        detected["chapters_glob"] = "chapters/*.tex"
    return detected


def _list(v: Any, default: list[str]) -> list[str]:
    return [str(x) for x in v] if isinstance(v, list) else default


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _pair(v: Any) -> tuple[int, int] | None:
    return (int(v[0]), int(v[1])) if isinstance(v, list) and len(v) == 2 else None


def load_config(workspace: str | Path) -> WorkbenchConfig:
    ws = Path(workspace).expanduser().resolve()
    cfg = WorkbenchConfig(workspace=ws, title=ws.name)
    for k, v in _auto_detect(ws).items():
        setattr(cfg, k, v)
    cfg.key_path = os.environ.get("ATW_SIGNING_KEY", "")

    toml_path = ws / "thesis.toml"
    if not toml_path.is_file():
        return cfg
    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    plan_rel = str(data.get("project", {}).get("plan", ""))
    if plan_rel and (ws / plan_rel).is_file():
        cfg.plan_file = plan_rel
        cfg.plan = tomllib.loads((ws / plan_rel).read_text(encoding="utf-8"))
        data = _deep_merge(data, cfg.plan)
    cfg.raw = data

    proj = data.get("project", {})
    cfg.title = proj.get("title", cfg.title)
    cfg.author = proj.get("author", cfg.author)
    cfg.language = proj.get("language", cfg.language)
    cfg.ui_locale = str(data.get("ui", {}).get("locale", cfg.ui_locale))

    fmt = data.get("format", {})
    cfg.format_adapter = fmt.get("adapter", cfg.format_adapter)
    cfg.chapters_glob = fmt.get("chapters_glob", cfg.chapters_glob)
    cfg.exclude_dirs = sorted(set(DEFAULT_EXCLUDE) | set(_list(fmt.get("exclude_dirs"), [])))
    cfg.exclude_files = _list(fmt.get("exclude_files"), cfg.exclude_files)
    cfg.compiler = fmt.get("compiler", cfg.compiler)
    cfg.compile_command = _list(fmt.get("compile_command"), cfg.compile_command)
    cfg.expected_sections = fmt.get("expected_sections", cfg.expected_sections)
    pages = fmt.get("pages") if isinstance(fmt.get("pages"), dict) else {}
    cfg.page_limit = pages.get("limit", fmt.get("page_limit", cfg.page_limit))
    cfg.pages_pdf = pages.get("pdf", cfg.pages_pdf)
    cfg.pages_aux = pages.get("aux", cfg.pages_aux)
    cfg.pages_aux_label = pages.get("aux_label", cfg.pages_aux_label)
    ptargets = pages.get("targets", {})
    if isinstance(ptargets, dict):
        for k, v in ptargets.items():
            if isinstance(v, list) and len(v) == 2:
                if k == "default":
                    cfg.page_limit = int(v[1])
                    cfg.page_targets.setdefault(0, (int(v[0]), int(v[1])))
                elif str(k).isdigit():
                    cfg.page_targets[int(k)] = (int(v[0]), int(v[1]))
    targets = fmt.get("word_targets", {})
    if isinstance(targets, dict):
        if isinstance(targets.get("default"), list) and len(targets["default"]) == 2:
            cfg.default_word_target = (int(targets["default"][0]), int(targets["default"][1]))
        for k, v in targets.items():
            if str(k).isdigit() and isinstance(v, list) and len(v) == 2:
                cfg.word_targets[int(k)] = (int(v[0]), int(v[1]))

    cit = data.get("citations", {})
    cfg.citation_provider = cit.get("provider", cfg.citation_provider)
    cfg.bib_file = cit.get("bib_file", cfg.bib_file)
    cfg.csl_file = cit.get("csl_file", cfg.csl_file)
    cfg.library_dir = cit.get("library_dir", cfg.library_dir)
    cfg.citation_syntax = cit.get("syntax", cfg.citation_syntax)
    cfg.ledger_file = cit.get("ledger_file", cfg.ledger_file)
    if isinstance(cit.get("aliases"), dict):
        cfg.citation_aliases = {str(k).lower(): str(v) for k, v in cit["aliases"].items()}

    ag = data.get("agents", {})
    for name in ("dialogue_dir", "dialogue_profile", "proposals_file", "comments_dir", "tasks_dir",
                 "reviews_dir", "style_guide_file", "moderator_name"):
        setattr(cfg, name, str(ag.get(name, getattr(cfg, name))))
    cfg.roles_dirs = _list(ag.get("roles_dirs"), cfg.roles_dirs)
    cfg.sign_decisions = bool(ag.get("sign_decisions", cfg.sign_decisions))
    cfg.require_key_path = bool(ag.get("require_key_path", cfg.require_key_path))
    cfg.key_path = cfg.key_path or str(ag.get("key_path", ""))

    cfg.plugin_dirs = _list(data.get("plugins", {}).get("dirs"), cfg.plugin_dirs)
    ctxc = data.get("context", {}) if isinstance(data.get("context"), dict) else {}
    cfg.context_chapter_files = _list(ctxc.get("chapter_files"), cfg.context_chapter_files)
    cfg.context_thesis_files = _list(ctxc.get("thesis_files"), cfg.context_thesis_files)
    cfg.context_memory_files = _list(ctxc.get("memory_files"), cfg.context_memory_files)

    # The author's chapters: [chapter_defaults] and [[chapters]] (pages, words, sections, narrative, ...)
    defaults = data.get("chapter_defaults", {}) if isinstance(data.get("chapter_defaults"), dict) else {}
    if _pair(defaults.get("pages")):
        cfg.page_targets[0] = _pair(defaults["pages"])
        cfg.page_limit = cfg.page_targets[0][1]
    if _pair(defaults.get("words")):
        cfg.default_word_target = _pair(defaults["words"])
    if isinstance(defaults.get("sections"), int):
        cfg.expected_sections = defaults["sections"]
    for ch in data.get("chapters", []) if isinstance(data.get("chapters"), list) else []:
        if not isinstance(ch, dict) or not str(ch.get("number", "")).isdigit():
            continue
        n = int(ch["number"])
        cfg.chapter_specs[n] = {k: v for k, v in ch.items() if k != "number"}
        if _pair(ch.get("pages")):
            cfg.page_targets[n] = _pair(ch["pages"])
        if _pair(ch.get("words")):
            cfg.word_targets[n] = _pair(ch["words"])
        if isinstance(ch.get("sections"), int):
            cfg.sections_by_chapter[n] = ch["sections"]

    qual = data.get("quality", {})
    cfg.quality_packs = _list(qual.get("packs", qual.get("presets")), cfg.quality_packs)
    cfg.disabled_checks = _list(qual.get("disabled_checks"), cfg.disabled_checks)
    if qual.get("max_sentence_words") is not None:
        cfg.max_sentence_words = int(qual["max_sentence_words"])
    cfg.forbid_first_person = bool(qual.get("forbid_first_person", cfg.forbid_first_person))
    cfg.spelling_variant = str(qual.get("spelling_variant", cfg.spelling_variant))
    cfg.prohibited_phrases = _list(qual.get("prohibited_phrases"), cfg.prohibited_phrases)
    cfg.emphasis_words = _list(qual.get("emphasis_words"), cfg.emphasis_words)
    if isinstance(qual.get("options"), dict):
        cfg.quality_options = dict(qual["options"])
    return cfg
