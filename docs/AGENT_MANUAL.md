# Agent Manual — Operating & Customizing Agentic Thesis Workbench

This manual is the canonical reference for **any AI agent** (CLI, IDE, cloud, or local model) collaborating on a thesis managed by **Agentic Thesis Workbench**.

---

## 1. Non-Negotiable Governance Rules

1. **Human-in-the-Loop Gate:** Never edit thesis manuscript files directly unless the corresponding question (`Qn`) has an `APPROVED` moderator decision recorded in the dialogue thread.
2. **Append-Only History:** Never delete, rewrite, or reorder previous turns in dialogue files (`.thesis/dialogue/*.md`). Always append a new turn at the bottom of the file.
3. **Model-Agnostic Identity:** Identify yourself clearly in every turn header — any model or platform name is accepted:
   ```markdown
   ## Turn N — <Agent or Tool Name> (<Model Name>) — YYYY-MM-DD
   ```
4. **Before/After Proposals:** When proposing a manuscript edit, always state:
   - Exact file path and section/line range
   - Current text
   - Proposed replacement text
   - Rationale and documentary evidence
5. **Verified Citations Only:** Never introduce a citation without confirming the source exists in the bibliography and recording the supporting passage in `.thesis/citations/ledger.json`.

---

## 2. Standard Turn Format

Append turns in this exact structure so the workbench parser indexes your questions and verdicts deterministically:

```markdown
## Turn 2 — Reviewer Agent (Model X) — 2026-11-26

**Q1 — Clarify scope of Chapter 1**
- **Verdict:** `AGREE` | `PARTIALLY AGREE` | `DISAGREE`
- **Evidence:** `chapters/01_introduction.md`, Section 1.2
- **Proposal:** Narrow the research question to two measurable hypotheses.

| # | Topic | State | Owner | Summary |
|---|---|---|---|---|
| Q1 | Clarify scope of Chapter 1 | `AGENT_CONSENSUS` | Author | Ready for approval |
```

Canonical question states:
- `OPEN` — Needs agent input
- `AGENT_CONSENSUS` — Agents agree; awaiting author approval
- `AGENT_DEADLOCK` — Agents disagree; awaiting author ruling
- `AUTHOR_RESERVED` — Strategic decision reserved for the author
- `SINGLE_PROPOSAL` — Proposed by one agent; awaiting review
- `APPROVED` — Approved by the human moderator (HMAC-SHA256 sealed when recorded via the UI)

---

## 3. How to Customize the Workbench on User Request

Authors may ask you to adapt citation formats, writing rules, terminology, or chapter structure. **Do not hardcode changes into the workbench engine** — update the workspace configuration instead:

### A. Change Thesis Format or Chapter Layout
Edit `thesis.toml` under `[format]`:
- `adapter`: `"markdown-latex"` | `"latex"` | `"markdown"`
- `chapters_glob`: glob matching chapter files (e.g. `"chapters/*.tex"` or `"[0-9][0-9]_CHAPTER_*/*.md"`)
- `word_targets`: per-chapter `[min, max]` word budgets (e.g. `1 = [3000, 3500]`)
- `expected_sections`: integer (optional) if the author enforces a fixed section count per chapter
- `page_limit`: integer (optional) maximum pages per chapter

### B. Change Citation Provider or Citation Syntax
Edit `thesis.toml` under `[citations]`:
- **BibTeX:** `provider = "bibtex"`, `bib_file = "references.bib"`
- **CSL-JSON (Zotero / Mendeley):** `provider = "csl-json"`, `csl_file = "references.json"`
- **Citation syntax:**
  - `"author-year"` for `(Smith, 2024)`
  - `"pandoc"` for `[@smith2024]`
  - `"latex"` for `\cite{smith2024}` / `\parencite{smith2024}`
- **Custom aliases:** add `[citations.aliases]` to map shorthand citations to canonical bibliography keys.

### C. Change Writing Style, Spelling, or Glossary Rules
1. Edit `thesis.toml` under `[quality]`:
   - `max_sentence_words = 40` (adjust sentence length threshold)
   - `forbid_first_person = true` (set `false` if first-person voice is allowed)
   - `spelling_variant = "en-GB"` (`"en-US"`, `"en-GB"`, or `"none"`)
   - `prohibited_phrases = [...]`
   - `emphasis_words = [...]`
2. Edit `.thesis/style/guide.json` to add approved terminology or style conventions:
   ```json
   {
     "thread": "STYLE_PLAN.md",
     "q": "Q8",
     "kind": "Term",
     "title": "Life-cycle hyphenation",
     "options": {
       "Option A": {
         "preferred": "life-cycle",
         "variants": ["lifecycle", "life cycle"]
       }
     }
   }
   ```

### D. Record Verified Citation Passages
Add verified passages to `.thesis/citations/ledger.json`:
```json
{
  "version": 1,
  "entries": [
    {
      "key": "smith2024",
      "chapter": 1,
      "claim": "Deterministic pipelines improve reproducibility.",
      "source": "LITERATURE/smith2024/full_text.md",
      "verdict": "supports"
    }
  ]
}
```
Valid verdicts: `"supports"`, `"partial"`, `"does_not_support"`.

---

## 4. Verification Command

After any configuration or approved manuscript update, run:

```bash
python3 -m atw check --workspace /path/to/thesis
```
