# Demo thesis — *Adaptive Irrigation Scheduling from Low-Cost Soil Sensors*

A small, **entirely fictional** thesis that exercises every part of the workbench. The author (Jane Researcher),
the references, the source texts and the field results are invented. Use it to try the workbench, or as a model
for laying out your own thesis.

```bash
# from the repository root
ATW_SIGNING_KEY=examples/demo-thesis/.thesis/demo-signing.key python3 -m atw serve --workspace examples/demo-thesis
# open http://127.0.0.1:8765
```

## What is in it

| Path | What it shows |
|------|---------------|
| `chapters/0N_*.md` | Five single-file chapters in Markdown with author-year citations. Some sentences break the plan's rules on purpose (first person, a prohibited phrase, an emphasis word, long sentences). |
| `references.bib` | Six fictional works. `(Hartmann, 2018)` is cited in Chapter 2 but has no entry, so it shows as unresolved. |
| `sources/<key>/full_text.md` | The archived text of four works. `Brennan2019` deliberately holds the wrong work, so it shows as *Does not match*. |
| `.thesis/plan.toml` | Jane's plan: pages and words per chapter, what each chapter must argue, writing rules. |
| `.thesis/dialogue/*.md` | Two agent discussions: questions in consensus, deadlock, reserved for the author, single proposal, one sealed approval each, and one approval an agent wrote itself (flagged as unauthorised). |
| `.thesis/comments/CH*.json` | Six comments by the author: open, answered by an agent with a before/after proposal, accepted (sealed), and a suggestion. |
| `.thesis/proposals/proposals.json` | Three change proposals: one approved (sealed), one rejected, one pending. |
| `.thesis/tasks`, `.thesis/reviews` | Two agent tasks and their validated outputs: a proposal drafter (Claude Code) and an independent tone reviewer (Gemini CLI). |
| `.thesis/citations/ledger.json` | Four sentences checked against the passage of their source: supports, partial and does not support. |
| `.thesis/style/guide.json` | Two terms; one counts because its question was approved with a sealed decision. |
| `.thesis/demo-signing.key` | **A throwaway key committed only so the demo's seals verify.** A real thesis keeps its key outside the repository. |

Everything under `.thesis/` that carries a seal was produced through the workbench's own API and CLI
(`atw task new`, `atw review validate`, the *Approve* and *Accept* actions), not written by hand.

To regenerate the screenshots in `docs/screenshots/`: `python3 scripts/screenshots.py` (needs Playwright).
