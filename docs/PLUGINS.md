# Plugins

Three kinds of extension, all discovered without extra dependencies:

| Kind | What it adds | How |
|---|---|---|
| **Check** | a quality rule | `@reg.check(...)` in a Python plugin |
| **Format / citation provider** | a thesis layout or a bibliography source | `@reg.format(id)` / `@reg.citation_provider(id)` |
| **Role** | a template for a sub-agent | `ROLE.md` file (no code) |

## Where plugins come from

1. Built-ins in `atw/builtin/` (they use the same contract as yours).
2. Installed packages exposing the entry-point group **`atw.plugins`** (and **`atw.roles`** for role folders),
   discovered with the standard `importlib.metadata`:

   ```toml
   # pyproject.toml of your package
   [project.entry-points."atw.plugins"]
   apa7 = "my_pack.apa7"
   [project.entry-points."atw.roles"]
   my_roles = "my_pack"          # roles in my_pack/roles/<id>/ROLE.md
   ```
3. Local files in the thesis: `.thesis/plugins/*.py` (folder list: `[plugins] dirs`), roles in `.thesis/roles/`.

Later sources override earlier ids. **Local plugins are code from the thesis repository and run with your
permissions** — only use plugin folders you trust.

## Contract

```python
PLUGIN = {"id": "my.pack", "version": "1.0", "api_version": 1, "description": "…"}

def register(reg):
    @reg.check("long_paragraph", group="Writing", label="Long paragraphs",
               rule="Paragraphs above 200 words", pack="my-pack", fail="warn", scope="chapter")
    def long_paragraph(ctx, ch):
        limit = ctx.option("paragraph_words", 200)       # from [quality.options]
        out = []
        for sec in ctx.sections[ch.number]:
            for no, line in sec.rows("prose"):
                if len(line.split()) > limit:
                    out.append(sec.item(no, f"{len(line.split())} words"))
        return out
```

- A check returns a list of findings (`{"file", "line", "text", "detail"}`; `sec.item(line, detail)` builds one),
  or a dict `{"state", "items", "count", "note"}` to set the state itself (`ok`, `warn`, `bad`, `na`).
- `scope="thesis"` checks receive only `ctx`.
- Checks run only when their `pack` is listed in `[quality] packs`; single checks can be turned off with
  `[quality] disabled_checks`.
- An exception inside a check shows that check as `error`; the others still run. A plugin whose
  `api_version` differs is skipped and listed in `atw plugins`.

`ctx` gives: `cfg`, `chapters`, `sections[n]` (lines, kinds — `heading`, `prose`, `list`, `table`, `caption`,
`image`, `fence` — `rows(*kinds)`, `neighbour`, `num`, `is_conclusion`), `citations`, `citation_uses[n]`,
`known_refs`, `style_guide`, `questions`, `reviews`, `option(name, default)`.

## Format adapters

```python
from atw.formats import FormatAdapter

class TypstAdapter(FormatAdapter):
    id = "typst"
    def normalise(self, raw):            # expose the text to checks as Markdown-like text
        return raw.replace("= ", "# ")

def register(reg):
    reg.format("typst")(TypstAdapter)
```

Then `[format] adapter = "typst"`.

## Roles

See `atw/roles/*/ROLE.md` for examples and [AGENT_MANUAL.md](AGENT_MANUAL.md) for how agents run them.
Front matter keys: `name`, `description` (both compatible with Agent Skills `SKILL.md`), `writes`
(`reviews` | `proposals` | `applied` | `dialogue`), `independent`, `fills_check`, `inputs`, `tools`.
