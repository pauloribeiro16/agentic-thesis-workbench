#!/bin/sh
# Open the workbench for this thesis. Uses a vendored copy in agentic-thesis-workbench/ when present
# (python3 -m atw vendor --workspace .), otherwise the installed one.
cd "$(dirname "$0")/.."
[ -d agentic-thesis-workbench/atw ] && export PYTHONPATH=agentic-thesis-workbench
exec python3 -m atw serve --workspace . --port "${1:-8765}"
