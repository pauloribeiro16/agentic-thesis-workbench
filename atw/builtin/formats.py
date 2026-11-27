"""Built-in format adapters and citation providers."""
from __future__ import annotations

from ..citations import _parse_bibtex, _parse_csl_json
from ..formats import FormatAdapter, LatexAdapter

PLUGIN = {"id": "builtin.formats", "version": "1.0", "api_version": 1,
          "description": "Markdown, Markdown+LaTeX, Quarto and LaTeX layouts; BibTeX, CSL-JSON, Zotero and Mendeley."}


class MarkdownLatexAdapter(FormatAdapter):
    id = "markdown-latex"


class QuartoAdapter(FormatAdapter):
    id = "quarto"


def register(reg) -> None:
    reg.format("markdown")(FormatAdapter)
    reg.format("markdown-latex")(MarkdownLatexAdapter)
    reg.format("quarto")(QuartoAdapter)
    reg.format("latex")(LatexAdapter)
    reg.citation_provider("bibtex")(_parse_bibtex)
    reg.citation_provider("csl-json")(_parse_csl_json)
    # Zotero and Mendeley: `atw library sync` writes the library as CSL-JSON to csl_file, read like csl-json
    reg.citation_provider("zotero")(_parse_csl_json)
    reg.citation_provider("mendeley")(_parse_csl_json)
