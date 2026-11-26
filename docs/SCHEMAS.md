# File formats

All files are JSON (UTF-8) inside the thesis repository. Paths are relative to the thesis root.

## Task packet — `.thesis/tasks/T-NNN.json` (written by the workbench)

```json
{
  "id": "T-012", "created": "2026-11-26T22:10:00", "created_by": "Author", "status": "open",
  "role": "proposal-drafter", "role_file": ".../ROLE.md", "writes": "proposals", "independent": false,
  "fills_check": "", "parent": null, "chapter": 3,
  "files": ["chapters/03_method.md"],
  "inputs": {"style_guide": "...", "ledger": "...", "dialogue_dir": "...", "thesis_toml": "thesis.toml"},
  "comments": [{"id": "C-1a2b3c4d", "file": "...", "quote": "...", "kind": "fix", "text": "...", "replies": []}],
  "approved_changes": [{"comment_id": "C-...", "file": "...", "quote": "...", "replacement": "..."}],
  "output": ".thesis/reviews/T-012.json"
}
```

`status` becomes `done` or `invalid` (with `errors`) after `atw review validate`.

## Output — `.thesis/reviews/T-NNN.json` (written by the agent)

Common fields: `task` (the id), `kind`, `role`, `agent: {"name", "model"}`, and `"independent": true`
for independent roles.

**`kind: "review"`** (roles that write `reviews` or `dialogue`)

```json
{"task": "T-013", "kind": "review", "role": "tone-reviewer", "agent": {"name": "Reviewer", "model": "X"},
 "independent": true, "summary": "Overall tone …",
 "findings": [{"file": "chapters/03_method.md", "line": 42, "quote": "exact words",
               "severity": "info|warn|bad", "category": "hedging", "problem": "…", "suggestion": "…"}]}
```

**`kind: "proposals"`** — every `quote` must appear exactly once in its file.

```json
{"task": "T-012", "kind": "proposals", "role": "proposal-drafter", "agent": {"name": "Drafter"},
 "proposals": [{"comment_id": "C-1a2b3c4d", "file": "...", "quote": "current text", "replacement": "new text",
                "rationale": "why"}]}
```

**`kind: "applied"`** — only comment ids listed in the packet's `approved_changes`; the replacement must
already be in the file.

```json
{"task": "T-014", "kind": "applied", "role": "implementer", "agent": {"name": "Implementer"},
 "applied": [{"comment_id": "C-1a2b3c4d", "note": "optional"}]}
```

## Comments — `<comments_dir>/CH<n>.json`

```json
{"version": 1, "chapter": 3, "comments": [{
  "id": "C-1a2b3c4d", "file": "chapters/03_method.md",
  "quote": "exact raw text", "prefix": "text before", "suffix": "text after", "pos": 1234,
  "author": "Author", "date": "2026-11-26T22:00:00", "kind": "fix|question|cite|style|suggest|note",
  "text": "the comment", "status": "open|addressed|approved|applied|resolved|wontfix",
  "replies": [{"author": "...", "date": "...", "text": "..."}],
  "proposal": {"quote": "...", "replacement": "...", "rationale": "...", "by": "...", "task": "T-012",
               "approved_by": "Author", "approved_at": "...", "seal": "<hmac>"},
  "history": [{"date": "...", "by": "...", "status": "..."}]
}]}
```

Anchoring follows the W3C Web Annotation selectors (TextQuote + TextPosition): exact match first
(context and position break ties), then fuzzy match (≥ 75 % similar), otherwise `orphan`.

## Citation ledger — `ledger_file`

```json
{"version": 1, "entries": [{
  "key": "smith2024", "file": "chapters/01_intro.md", "claim": "the sentence in the thesis",
  "source": "LITERATURE/smith2024/full_text.md", "start": 1200, "end": 1460, "sha256": "<of the passage>",
  "verdict": "supports|partial|does_not_support"
}]}
```

`source` may start with `lit:` to be relative to `library_dir`. When `start`, `end` and `sha256` are present,
the passage is re-hashed on every check, so an edited source shows up as a problem.

## Style guide — `style_guide_file`

```json
{"version": 1, "entries": [{
  "thread": "STYLE_PLAN.md", "q": "Q8", "kind": "Term", "title": "Life-cycle",
  "options": {"Option A": {"preferred": "life-cycle", "variants": ["lifecycle", "life cycle"]},
              "Option B": {"preferred": "life cycle", "variants": ["life-cycle", "lifecycle"]}}
}]}
```

A term counts only once question `q` in `thread` is approved with a sealed decision. The chosen option is
read from the decision note (`Chosen option: Option B`); otherwise the first option applies.

## Change proposals — `[agents] proposals_file`

Concrete before/after edits not tied to a comment (written by agents such as `condenser`, or by
`proposal-drafter` when a proposal has no `comment_id`).

```json
{"version": 1,
 "topics": [{"id": "t1", "thread": "CH3_PLAN.md", "q": "Q1", "title": "Running example", "why": "…"}],
 "items": [{"id": "P-1a2b3c", "topic": "t1", "file": "chapters/03.md", "old": "current text", "new": "new text",
            "desc": "why", "status": "pending|approved|rejected|applied", "decision": "kept|contested",
            "parent": null, "registered": null, "by": "agent", "task": "T-012", "seal": "<hmac>"}]}
```

Verdict: `pending` / `approved` / `rejected` before the text changes; once `applied`, `review` until the author
keeps (`kept`) or contests (`contested`) it. Approving seals the item. *Register* appends one sealed moderator
block per topic thread listing the decisions, and marks the items `registered`. The implementer receives
approved, sealed items as `approved_changes` with `change_id` and reports them in `applied`.

## Page budget — `[format.pages]`

`targets = { default = [20, 25], 1 = [12, 16] }` sets the pages per chapter (without references; the count
stops at `aux_label`, or uses the whole `pdf`). In-text citations are taken out of the estimate by their share
of the body text. Each chapter's words per page come from its last PDF, so the live word count becomes a page
estimate and "words that fit". `compile_command` (with `{chapter}`) refreshes the PDF from the UI; if a JSON
file with the PDF's name exists, it is shown as the build report.
