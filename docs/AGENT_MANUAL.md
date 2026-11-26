# Agent Manual

How any AI agent (CLI, IDE, cloud or local model) works on a thesis managed by Agentic Thesis Workbench.
The workbench never runs agents itself: it publishes **tasks**, agents run **roles**, and the workbench
**validates** what comes back. Everything is plain files in the thesis repository.

## 1. Rules that never change

1. **Do not edit chapter files** — unless you are running the `implementer` role, and then only the
   approved, sealed changes listed in your task packet.
2. **Agents propose, the author decides.** You may set a question to `AGENT_CONSENSUS`, `AGENT_DEADLOCK`,
   `SINGLE_PROPOSAL` or `AUTHOR_RESERVED`. Only a moderator decision block with a valid HMAC seal (written
   by the workbench when the author clicks *Approve*) makes a question `APPROVED`. If you write `APPROVED`
   in a table, it is shown as an unauthorised claim and ignored.
3. **Dialogue is append-only.** Never edit or delete earlier turns.
4. **Cite only verified passages.** A citation needs a supporting passage in the ledger.
5. **Change rules through configuration**, never in the engine (see §5).

## 2. Doing a task

The author creates tasks from the web UI (Manuscript, Quality or Agents) or the CLI:

```bash
python3 -m atw task new --workflow chapter-review --chapter 3 --workspace <thesis>
python3 -m atw task new --role tone-reviewer --chapter 3 --workspace <thesis>
```

When asked to "do T-012":

1. Read the packet `.thesis/tasks/T-012.json` (files, inputs, comments or approved changes, output path).
2. Load the role: `python3 -m atw roles show <role> --workspace <thesis>`.
3. Run it. **If your tool has sub-agents, run the role in a sub-agent** with the role text as its prompt
   (a workflow packet lists child tasks — run them in parallel, then consolidate).
4. Write the output JSON at the path in the packet (formats in [SCHEMAS.md](SCHEMAS.md)).
5. Validate: `python3 -m atw review validate T-012 --workspace <thesis>`. Fix every reported error.

To make roles native in your tool, export them once:

```bash
python3 -m atw roles export --to claude     # .claude/agents/<role>.md (sub-agents)
python3 -m atw roles export --to skills     # .agents/skills/<role>/SKILL.md (Agent Skills format)
python3 -m atw roles export --to markdown   # .thesis/prompts/<role>.md (paste anywhere)
```

Use `--dest` if your tool reads skills from another folder.

## 3. Built-in roles and workflows

| Role | Writes | Purpose |
|---|---|---|
| `chapter-auditor` | review | Runs the checks, drops false positives, ranks the 10 issues that matter most |
| `tone-reviewer` | review → check `tone` | Register, hedging, voice, unsupported evaluation |
| `narrative-reviewer` | review → check `narrative` | Argument thread, transitions, promises kept, links between chapters |
| `consistency-checker` | review → check `consistency` | Approved decisions and glossary reflected in the text |
| `citation-verifier` | review | Each sentence against the passage of the source it cites |
| `jury-examiner` | dialogue + review | The hardest examiner questions, opened as new questions |
| `condenser` | proposals | Cuts to fit the page or word budget |
| `proposal-drafter` | proposals | One before/after proposal per open comment |
| `implementer` | applied | Applies approved, sealed changes exactly |

Workflows: `chapter-review`, `close-comments`, `apply-approved`, `pre-submission`.
Add your own roles in `.thesis/roles/<id>/ROLE.md` and workflows as `[[workflows]]` in `thesis.toml`.

## 4. Comments and change proposals

**Change proposals** are before/after edits not tied to a comment. A proposals output without `comment_id`
becomes a pending change in `proposals_file`; the author approves or rejects it (sealed), the implementer
applies it, and edits already in the text without approval wait for the author to keep or contest them.

### The comment cycle

```
open ──proposal-drafter──▶ addressed ──author accepts──▶ approved ──implementer──▶ applied ──author confirms──▶ resolved
```

The author can reopen (with a note that goes back to you) or mark *won't do* at any step. An author's own
suggestion starts as `approved`. Approvals are sealed: editing the comments JSON does not approve anything.

## 5. Customising at the author's request

| The author wants… | Change |
|---|---|
| Another layout or format | `[format] adapter`, `chapters_glob`, `exclude_dirs`; a new format = a plugin |
| APA vs Pandoc vs LaTeX citations | `[citations] syntax = "author-year" \| "pandoc" \| "latex"` |
| Zotero / Mendeley | `[citations] provider = "csl-json"`, `csl_file` |
| Laws or standards cited without year | `[citations] no_year_keys = ["GDPR", …]` |
| Shorthand citations | `[citations.aliases] "nist, 2024" = "NISTCSF2024"` |
| Sentence length, first person, spelling | `[quality] max_sentence_words`, `forbid_first_person`, `spelling_variant` |
| Banned phrases / emphasis words | `[quality] prohibited_phrases`, `emphasis_words` |
| Glossary terms | style guide entry linked to an approved question (see SCHEMAS.md) |
| Pages, words, sections per chapter | the plan file: `[chapter_defaults]` and `[[chapters]]` (`pages`, `words`, `sections`, `narrative`) |
| Page measurement | `[format.pages]`, `pdf` or `aux` + `aux_label`; `[format] compile_command` for the PDF view |
| Turn a check off | `[quality] disabled_checks = ["emphasis"]` |
| A new rule | a check plugin in `.thesis/plugins/` (see [PLUGINS.md](PLUGINS.md)), in its own pack |
| A new reviewer | `.thesis/roles/<id>/ROLE.md` |

After any change run `python3 -m atw check --workspace <thesis>`.

### What is the author's and what is generic

Limits, chapter structure, chapter narratives and writing rules belong to the author: they live in the plan file
(`[project] plan`, e.g. `.thesis/plan.toml`) and in the thesis's own plugins. Never add them to the engine or
treat them as defaults for other theses. Task packets carry the chapter's plan as `chapter_plan` (including its
`narrative`), so reviewers judge the chapter against what the author wants it to argue.

## 6. Dialogue format

```markdown
## Turn 3 — <Agent name> (<Model>) — 2026-11-26

**Q4 — Clarify the scope of Chapter 1**
- **Verdict:** `AGREE` | `PARTIALLY AGREE` | `DISAGREE`
- **Evidence:** `chapters/01_introduction.md`, §1.2
- **Proposal:** current text → proposed text

| # | Topic | State | Owner | Summary |
|---|---|---|---|---|
| Q4 | Clarify the scope of Chapter 1 | `AGENT_CONSENSUS` | Author | ready for a decision |
```

Theses written with the older Portuguese vocabulary (`Vez`, `CONCORDO`, `APROVADA`) set
`[agents] dialogue_profile = "pt-legacy"`.
