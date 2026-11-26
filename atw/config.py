"""Configuration loader for Agentic Thesis Workbench (thesis.toml)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_WORD_TARGET = (6000, 7500)


@dataclass
class WorkbenchConfig:
    workspace: Path
    title: str = "Untitled Thesis"
    author: str = "Author"
    language: str = "en-US"

    # Format adapter
    format_adapter: str = "markdown-latex"
    chapters_glob: str = "[0-9][0-9]_*/**/*.md"
    latex_dir: str = ""
    compiler: str = "none"
    word_targets: dict[int, tuple[int, int]] = field(default_factory=dict)
    default_word_target: tuple[int, int] = DEFAULT_WORD_TARGET
    expected_sections: int | None = None
    page_limit: int | None = None

    # Citations adapter
    citation_provider: str = "bibtex"
    bib_file: str = ""
    csl_file: str = ""
    library_dir: str = "LITERATURE"
    citation_syntax: str = "author-year"
    integrity_manifest: str = ""
    citation_aliases: dict[str, str] = field(default_factory=dict)
    ledger_file: str = ".thesis/citations/ledger.json"

    # Agents & governance
    dialogue_dir: str = ".thesis/dialogue"
    proposals_file: str = ".thesis/proposals/proposals.json"
    comments_dir: str = ".thesis/comments"
    style_guide_file: str = ".thesis/style/guide.json"
    moderator_name: str = "Author"
    sign_decisions: bool = True
    key_path: str = ""
    papers_dir: str = ""

    # Quality rules
    quality_presets: list[str] = field(default_factory=lambda: ["academic-base"])
    max_sentence_words: int = 40
    forbid_first_person: bool = False
    spelling_variant: str = "none"  # none | en-GB | en-US
    prohibited_phrases: list[str] = field(default_factory=list)
    emphasis_words: list[str] = field(
        default_factory=lambda: [
            "crucial", "pivotal", "robust", "seamless", "delve",
            "leverage", "paramount", "comprehensive", "holistic",
            "landscape", "underscore", "novel",
        ]
    )
    raw: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "workspace": str(self.workspace),
            "project": {
                "title": self.title,
                "author": self.author,
                "language": self.language,
            },
            "format": {
                "adapter": self.format_adapter,
                "chapters_glob": self.chapters_glob,
                "latex_dir": self.latex_dir,
                "compiler": self.compiler,
                "default_word_target": list(self.default_word_target),
                "expected_sections": self.expected_sections,
                "page_limit": self.page_limit,
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
                "moderator_name": self.moderator_name,
                "sign_decisions": self.sign_decisions,
                "style_guide_file": self.style_guide_file,
            },
            "quality": {
                "presets": self.quality_presets,
                "max_sentence_words": self.max_sentence_words,
                "forbid_first_person": self.forbid_first_person,
                "spelling_variant": self.spelling_variant,
                "prohibited_phrases_count": len(self.prohibited_phrases),
                "emphasis_words_count": len(self.emphasis_words),
            },
        }


def _auto_detect(workspace: Path) -> dict[str, Any]:
    """Infer sensible defaults when a workspace has no thesis.toml yet."""
    detected: dict[str, Any] = {}
    if (workspace / "AGENT_DIALOGUE").is_dir():
        detected["dialogue_dir"] = "AGENT_DIALOGUE"
        detected["proposals_file"] = "AGENT_DIALOGUE/proposals/proposals.json"
        detected["comments_dir"] = "AGENT_DIALOGUE/comments"
        detected["ledger_file"] = "AGENT_DIALOGUE/citations/ledger.json"
        detected["style_guide_file"] = "AGENT_DIALOGUE/style/guide.json"

    bibs = sorted(workspace.rglob("*.bib"))
    bibs = [b for b in bibs if ".git" not in b.parts and "node_modules" not in b.parts]
    if bibs:
        detected["bib_file"] = str(bibs[0].relative_to(workspace))

    csls = sorted(workspace.glob("*.json"))
    for c in csls:
        if "csl" in c.name.lower() or "references" in c.name.lower():
            detected["csl_file"] = str(c.relative_to(workspace))
            if not bibs:
                detected["citation_provider"] = "csl-json"
            break

    if (workspace / "chapters").is_dir():
        mds = list((workspace / "chapters").glob("*.md"))
        texs = list((workspace / "chapters").glob("*.tex"))
        if texs and not mds:
            detected["format_adapter"] = "latex"
            detected["chapters_glob"] = "chapters/*.tex"
        elif mds:
            detected["chapters_glob"] = "chapters/*.md"

    return detected


def load_config(workspace: str | Path) -> WorkbenchConfig:
    ws = Path(workspace).expanduser().resolve()
    cfg = WorkbenchConfig(workspace=ws, title=ws.name)

    for k, v in _auto_detect(ws).items():
        setattr(cfg, k, v)

    toml_path = ws / "thesis.toml"
    if not toml_path.is_file():
        return cfg

    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    cfg.raw = data

    proj = data.get("project", {})
    cfg.title = proj.get("title", cfg.title)
    cfg.author = proj.get("author", cfg.author)
    cfg.language = proj.get("language", cfg.language)

    fmt = data.get("format", {})
    cfg.format_adapter = fmt.get("adapter", cfg.format_adapter)
    cfg.chapters_glob = fmt.get("chapters_glob", cfg.chapters_glob)
    cfg.latex_dir = fmt.get("latex_dir", cfg.latex_dir)
    cfg.compiler = fmt.get("compiler", cfg.compiler)
    cfg.expected_sections = fmt.get("expected_sections", cfg.expected_sections)
    cfg.page_limit = fmt.get("page_limit", cfg.page_limit)
    targets = fmt.get("word_targets", {})
    if isinstance(targets, dict):
        if "default" in targets and len(targets["default"]) == 2:
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
    cfg.integrity_manifest = cit.get("integrity_manifest", cfg.integrity_manifest)
    cfg.ledger_file = cit.get("ledger_file", cfg.ledger_file)
    if isinstance(cit.get("aliases"), dict):
        cfg.citation_aliases = {str(k).lower(): str(v) for k, v in cit["aliases"].items()}

    ag = data.get("agents", {})
    cfg.dialogue_dir = ag.get("dialogue_dir", cfg.dialogue_dir)
    cfg.proposals_file = ag.get("proposals_file", cfg.proposals_file)
    cfg.comments_dir = ag.get("comments_dir", cfg.comments_dir)
    cfg.style_guide_file = ag.get("style_guide_file", cfg.style_guide_file)
    cfg.moderator_name = ag.get("moderator_name", cfg.moderator_name)
    cfg.sign_decisions = bool(ag.get("sign_decisions", cfg.sign_decisions))
    cfg.key_path = ag.get("key_path", os.environ.get("ATW_SIGNING_KEY", cfg.key_path))
    cfg.papers_dir = ag.get("papers_dir", os.environ.get("ATW_PAPERS_DIR", cfg.papers_dir))

    qual = data.get("quality", {})
    if isinstance(qual.get("presets"), list):
        cfg.quality_presets = [str(p) for p in qual["presets"]]
    cfg.max_sentence_words = int(qual.get("max_sentence_words", cfg.max_sentence_words))
    cfg.forbid_first_person = bool(qual.get("forbid_first_person", cfg.forbid_first_person))
    cfg.spelling_variant = str(qual.get("spelling_variant", cfg.spelling_variant))
    if isinstance(qual.get("prohibited_phrases"), list):
        cfg.prohibited_phrases = [str(p) for p in qual["prohibited_phrases"]]
    if isinstance(qual.get("emphasis_words"), list):
        cfg.emphasis_words = [str(w) for w in qual["emphasis_words"]]

    return cfg
