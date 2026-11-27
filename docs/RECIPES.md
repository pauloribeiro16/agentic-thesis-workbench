# Recipes

Patterns that most theses need. The engine stays generic; the thesis provides the few lines specific to it.

## Carry the workbench inside the thesis

```bash
python3 -m atw vendor --workspace /path/to/thesis      # → /path/to/thesis/agentic-thesis-workbench/
sh /path/to/thesis/.thesis/serve.sh                     # created by `atw init`; uses the vendored copy
```

The copy is replaced as a whole each time and records its source commit in `.source-commit`. Do not edit code
inside it: improve the workbench repository and vendor again. Your data and rules stay outside the copy.

## Compile one chapter to PDF from the manuscript (LaTeX)

Point `[format] compile_command` at a small script in the thesis. The script should:

1. produce the chapter's `.tex` **from the current manuscript** (your Markdown → LaTeX generator), in memory;
2. write everything under a build folder (e.g. `.thesis/build/`) — never over the thesis's own LaTeX files;
3. wrap the chapter in your document class and put a label right after it, before the bibliography, so the
   page budget can stop there;
4. optionally write a JSON report next to the PDF (same name, `.json`): the workbench shows it in the PDF view.

```python
#!/usr/bin/env python3
"""python3 .thesis/build_chapter.py <n> — compile chapter n into .thesis/build/."""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / ".thesis" / "build"

def chapter_tex(n: int) -> str:
    # replace with your generator; it must return the LaTeX for chapter n from the Markdown
    return subprocess.run(["pandoc", *sorted(map(str, ROOT.glob(f"chapters/{n:02d}_*.md"))), "-t", "latex"],
                          capture_output=True, text=True, check=True).stdout

def main(n: int) -> int:
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / f"ch{n}.body.tex").write_text(chapter_tex(n), encoding="utf-8")
    (BUILD / f"ch{n}.tex").write_text(rf"""\\documentclass{{report}}
\\begin{{document}}
\\setcounter{{chapter}}{{{n - 1}}}
\\input{{ch{n}.body}}
\\label{{endofchapter}}
\\bibliographystyle{{plainnat}}\\bibliography{{../../references}}
\\end{{document}}""", encoding="utf-8")
    p = subprocess.run(["tectonic", "--keep-intermediates", f"ch{n}.tex"], cwd=BUILD)
    (BUILD / f"ch{n}.json").write_text(json.dumps({"ok": p.returncode == 0, "source": "markdown"}), encoding="utf-8")
    return p.returncode

if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1])))
```

```toml
[format]
compile_command = ["python3", ".thesis/build_chapter.py", "{chapter}"]

[format.pages]
aux = ".thesis/build/ch{chapter}.aux"
aux_label = "endofchapter"
pdf = ".thesis/build/ch{chapter}.pdf"
```

## Keep the stored LaTeX identical to the manuscript

If the thesis also stores the generated `.tex` (for example for the full-document build), check that it still
equals what the generator produces today:

```toml
[format.sync]
command = ["python3", "tools/md_to_tex.py", "--stdout", "{chapter}"]   # prints the generated text
target = "latex/chapters/ch{chapter}.tex"
```

The `generated_sync` check is `bad` when they differ and `warn` when a chapter has no generator (non-zero exit).
If your generator cannot print to standard output, write a small plugin with the same logic in `.thesis/plugins/`.

## Start a University of Minho thesis in LaTeX, with Zotero

```toml
[project]
title = "Your thesis title"
author = "Your Name"
[output]
base = "latex"
template = "uminho-phd"
[template]
school = "School of Engineering"
school_logo = "EE"
programme = "Doctoral Programme in …"
supervisor = "Professor …"
[citations]
provider = "zotero"
bib_export = "latex/references.bib"
```

```bash
python3 -m atw template apply --workspace .     # latex/dissertation.tex, covers, preamble, logos
python3 -m atw library sync --workspace .       # Zotero → references.json + latex/references.bib
cd latex && tectonic dissertation.tex           # copy the NewsGotT fonts into latex/fonts/ first
```

Add chapters as `latex/chapters/*.tex` and run `template apply` again to refresh the chapter list. When the official
Word model is available, save it as `.thesis/templates/uminho-phd/word/template.docx` and apply with `--base word`.
