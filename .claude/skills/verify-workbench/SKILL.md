---
name: verify-workbench
description: "Formally verify the Agentic Thesis Workbench: TLA+ models (TLC) of governance, comments, change proposals and task validation, conformance tests that replay every model row on the real code, property tests, every quality check both ways, API/CLI/security tests and the requirements traceability gate. Use whenever editing atw/dialogue.py, atw/comments.py, atw/changes.py, atw/tasks.py, atw/server.py, a quality check, a template, the library connectors, or verify/requirements.toml — and before every commit."
---

# Verify the workbench

1. Run `verify/run.sh`. It must end with `ALL VERIFIED`.
2. If you changed **who may change what** (states, approvals, seals, applying changes, validation):
   - update the `Step` of the matching model in `verify/*.tla` first, then the code;
   - keep the constants in the `.cfg` equal to the code (conformance tests compare them);
   - never weaken an invariant to make TLC pass — a violation is a defect until shown otherwise.
3. If you added or changed a capability, add or edit its requirement in `verify/requirements.toml` with at least one
   `verified_by` link (a TLA+ operator listed in a `.cfg`, or a test), then run `python3 verify/trace.py`.
4. A new quality check needs a test in `tests/test_checks_each.py` named `test_<check id>` (one breaking text, one
   clean text); the catalogue test fails otherwise.
5. Report the result honestly: which models were proved, how many conformance rows, what was skipped (no
   tectonic / node), and any defect found.
