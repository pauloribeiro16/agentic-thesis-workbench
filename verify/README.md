# Formal verification

```bash
verify/run.sh        # TLC on every model, the pre-fix variants (must fail), all tests, traceability
```

Needs `tlc` (TLA+ tools, Java). `tectonic` and `node` are optional (the template compile and the web-client tests
are skipped without them). Takes about three minutes.

## How it fits together

1. **Requirements** — [`requirements.toml`](requirements.toml) lists every requirement of the workbench (plus one per
   quality check, taken from the plugin registry): **130**. Each links to what verifies it.
2. **Models** — the stateful parts (who may change what, and when) are TLA+ specifications. TLC explores **every**
   reachable state and proves the invariants and temporal properties below.
3. **Link model ↔ code (conformance)** — each model defines `Step` (one action, exactly as the code does it) and a
   `Table`: every sequence of actions up to a bound with the model's result. [`tlc.py`](tlc.py) makes TLC print that
   table; the conformance tests replay **every row** on the real Python service and require the same result. Each
   test also checks that the constant the code uses is the one TLC proved. Mutating the code (e.g. dropping the
   claim an agent's approval records) makes the conformance test fail on 1 084 of 3 616 threads.
4. **Everything else** — property tests (laws on hundreds of generated inputs), every quality check both ways (a
   breaking text is reported, a clean one accepted), and end-to-end API, CLI, web-client and security tests.
5. **Traceability** — [`trace.py`](trace.py) checks that every requirement has a verification and every link
   resolves (a test that exists; an operator defined in the model and listed in that config), and writes
   [`docs/REQUIREMENTS.md`](../docs/REQUIREMENTS.md). `tests/test_traceability.py` fails otherwise.

## Models

| Model | Code | States (TLC) | Conformance rows | Proves |
|---|---|---|---|---|
| [`Governance.tla`](Governance.tla) | `atw/dialogue.py` | 324 signed · 339 unsigned | 3 616 × 2 | `ApprovedByAuthor`, `RejectedByAuthor`, `ApprovalSticks`, `AgentNeverSetsAuthorOnly`, `RefusalCounted` |
| [`CommentLifecycle.tla`](CommentLifecycle.tla) | `atw/comments.py` | 328 | 7 381 | `OnlyAuthorDecides`, `AgentOnlyProposes`, `ApprovedIsSealedOrTampered`, `AppliedWasSealed`, `AppliedMeansEdited` |
| [`ChangeLifecycle.tla`](ChangeLifecycle.tla) | `atw/changes.py` | 376 | 22 222 | `OnlyAuthorDecides`, `AppliedWasSealed`, `AppliedMeansEdited`, `RegisteredIsFinal`, `RegisteredWasDecided` |
| [`TaskValidation.tla`](TaskValidation.tla) | `atw/tasks.py` | 51 | 364 | `EffectsAtMostOnce`, `DoneMeansEffect`, `DoneStaysDone` |

Each `*_before_fix.cfg` is the rule as it was; `run.sh` requires TLC to **refute** it, so every defect below is
shown to be real by a counterexample.

## Defects found by the verification (all fixed)

| # | Found by | Defect | Fix |
|---|---|---|---|
| 1 | TLC (`Governance_before_fix`, 1 step) | An agent could close a question as **rejected** without the author: only `APPROVED` was author-only. | `REJECTED` is author-only too. |
| 2 | TLC (`CommentLifecycle_before_fix`, 4 steps) | A **deletion** (empty replacement) could be marked *applied* with the text untouched: `"" in text` is always true. | `text_shows`: the replacement is there **and** the replaced passage is gone. |
| 3 | Conformance (1 of 7 381 sequences) | An agent could **edit the stored proposal before the author accepted it**; accepting sealed the edited version and *apply* passed with the text untouched. The first model lacked this; it now has it. | Accepting needs the proposal's passage exactly once in the text. |
| 4 | TLC (`ChangeLifecycle_before_fix`) | The same path for change proposals. | Approving needs the old text exactly once in the file. |
| 5 | TLC (`TaskValidation_before_fix`) | Validating a task again **re-applied its effects** (duplicated proposals; a done task could turn invalid). | A done task is final. |
| 6 | Code reading for the model | A proposal answering a comment, in a task without a chapter, was silently dropped. | Reported by validation. |
| 7 | Check tests | The first-person check was case-sensitive: "**We** show…" at the start of a sentence was never flagged. | Capitalised forms matched (not "US"). |
| 8 | Security test | **Cross-site action**: a page on any site could POST from a sandboxed iframe (`Origin: null`) with `Content-Type: text/plain; x=application/json` (no CORS preflight) — and the server would **seal an approval with the author's key**. | `Origin: null` refused on actions; the JSON media type must be exact. |
| 9 | CLI tests | `atw task show <unknown>` exited 0. | Exits 2 with a message. |
| 10 | Browser check | A thesis without word targets crashed the state endpoint (500). | Fixed in `config.to_public_dict`. |

## What is and is not proved

- **Proved by TLC, for every reachable state of the model:** the invariants and properties in the table. The
  models are small by construction (one question, one comment, one change, one task) because each item is
  independent of the others in the code.
- **Linked to the code, row by row:** every sequence up to 3 writes (governance), 4 actions (comments, changes) or 5
  actions (tasks). Longer sequences are covered by the model, not replayed on the code.
- **Assumed, not proved:** HMAC-SHA256 is a secure MAC (the property tests check that the code uses it so that any
  change is detected); the file system and the Python runtime behave as documented.
- **Verified by tests, not by a model:** the quality checks (each both ways), templates, the reference-manager
  connectors (HTTP faked: not run against a live Zotero or Mendeley), the API, CLI and security rules, and the
  parts of the web client that run without a browser (question excerpts, texts in both languages, views).
