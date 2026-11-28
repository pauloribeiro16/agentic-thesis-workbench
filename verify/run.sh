#!/bin/sh
# Formal verification of the workbench, end to end. Usage: verify/run.sh  (needs tlc + Java; tectonic and node optional)
#  1. TLC proves every invariant/property of every model (verify/*.cfg)
#  2. TLC must find the defect in each "_before_fix" variant (the defects the verification found were real)
#  3. all tests: conformance (code = model, row by row), properties, every check both ways, API/CLI/security
#  4. traceability: every requirement verified, every link resolves, docs/REQUIREMENTS.md current
set -e
cd "$(dirname "$0")"
command -v tlc >/dev/null || { echo "tlc not found (TLA+ tools): see verify/README.md"; exit 2; }
meta=$(mktemp -d)
trap 'rm -rf "$meta"' EXIT
fail=0

prove() {  # module config
  out=$(tlc -workers auto -metadir "$meta/$2" -config "$2.cfg" "$1.tla" 2>&1 || true)
  if echo "$out" | grep -q "No error has been found"; then
    printf '  proved   %-28s %s\n' "$2" "$(echo "$out" | grep -o '[0-9]* distinct states found')"
  else
    printf '  FAILED   %s\n' "$2"; echo "$out" | grep -E "violated|Error" | head -5; fail=1
  fi
}
refuted() {  # module config — the old rule must be broken
  out=$(tlc -workers auto -metadir "$meta/$2" -config "$2.cfg" "$1.tla" 2>&1 || true)
  if echo "$out" | grep -q "is violated"; then
    printf '  refuted  %-28s %s\n' "$2" "$(echo "$out" | grep -o 'Invariant [A-Za-z]* is violated')"
  else
    printf '  NOT REFUTED %s (the old rule should fail)\n' "$2"; fail=1
  fi
}

echo "== 1. TLC: invariants and properties"
prove Governance Governance_signed
prove Governance Governance_unsigned
prove CommentLifecycle CommentLifecycle
prove ChangeLifecycle ChangeLifecycle
prove TaskValidation TaskValidation

echo "== 2. TLC: the rules before the fixes are broken"
refuted Governance Governance_before_fix
refuted CommentLifecycle CommentLifecycle_before_fix
refuted ChangeLifecycle ChangeLifecycle_before_fix
refuted TaskValidation TaskValidation_before_fix

cd ..
echo "== 3. tests (conformance, properties, checks, API/CLI/security)"
if python3 -m unittest discover -s tests 2>"$meta/tests.log" >/dev/null; then :; else fail=1; fi
grep -E "^(Ran|OK|FAILED|FAIL:|ERROR:)" "$meta/tests.log" | sed 's/^/  /'

echo "== 4. traceability"
python3 verify/trace.py --check > "$meta/trace.log" || fail=1
sed 's/^/  /' "$meta/trace.log"

[ $fail -eq 0 ] && echo "ALL VERIFIED" || { echo "VERIFICATION FAILED"; exit 1; }
