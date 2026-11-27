# Word base — slot for the official template

The workbench can produce the thesis from a Word template, but the official UMinho doctoral `.docx` is not
shipped here. When you have it:

1. Save it as `word/template.docx` in this folder, or — to keep it out of the workbench copy — as
   `<thesis>/.thesis/templates/uminho-phd/word/template.docx`.
2. In `thesis.toml` set `[output] base = "word"`.
3. Run `python3 -m atw template apply --workspace <thesis>`.

The workbench copies the template to `[output] dir` and fills its document properties (title, author) and any
`{{field}}` placeholders written in the template's text with the values from `thesis.toml`.
