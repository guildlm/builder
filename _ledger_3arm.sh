#!/usr/bin/env bash
# One hole, two rival remedies, one process. Nobody has run them against each other.
#
# ledger's spec names SEVEN store tests; the shipped artifact has SIX. The missing
# one, TestCreateTransactionMovesBalances, is the only test that asserts the CREDIT
# side of a posting lands — and without it, a store that silently drops every
# credit (money vanishing from a double-entry ledger) passes build, vet and the
# ENTIRE suite. Measured 2026-07-17, deterministically, with no model involved.
#
# There are exactly two known remedies for "the model drops a test the spec NAMES":
#   the completeness RULE  — its one confirmed benefit is this exact failure
#                            (workapi's TestListSorted, 3/3). It is OFF by default
#                            because it costs shortener its green (5/5).
#   the SPEC FIX           — replace the prose with the code. Six instances, and
#                            today's guard landed byte-identically 2/2. But a spec
#                            edit is not free: today it deterministically DELETED a
#                            spec-named test from a file generated EARLIER, 2/2
#                            with names and 2/2 without.
#
# WHY THE CONTROL ARM EXISTS, and why it is not optional: the artifact that showed
# the hole was built 07-15 19:24, in a different process, on a builder twelve
# commits back. Comparing a new run against it would pool across processes AND
# builder versions — the exact error that killed a story this morning. If arm A
# writes the test, the hole is already closed and the spec fix is pure cost.
#
# Every arm keeps its artifact under its own name. A tool of mine already
# destroyed one arm's evidence today by reusing a fixed path; this one does not.
#
# Usage: _ledger_3arm.sh
set -uo pipefail
cd "$(dirname "$0")"

OLD=/tmp/ledger-OLD.yaml     # the spec as it was when the hole was found
NEW=/tmp/ledger-NEW.yaml     # prose replaced with the code (committed af1932d)
for f in "$OLD" "$NEW"; do
  [ -s "$f" ] || { echo "missing $f — stage both spec versions first"; exit 2; }
done
SUM="logs/ledger-3arm-$(date +%m%d%H%M).log"
: > "$SUM"

# Restore the committed spec whatever happens — a crashed run must not leave the
# tree holding an experimental arm that a later commit would silently ship.
trap 'cp "$NEW" specs/ledger.yaml; echo "[restored committed spec]" >> "$SUM"' EXIT

run_arm () {          # name, spec-file, GUILDLM_ENABLE_RULES value
  local name="$1" spec="$2" rules="$3"
  echo "########## ARM $name  (rules='${rules:-none}') ##########" >> "$SUM"
  cp "$spec" specs/ledger.yaml
  GUILDLM_ENABLE_RULES="$rules" ./_ab_run.sh ledger >> "$SUM" 2>&1
  local keep="./generated/_ledger-ARM-${name}"
  rm -rf "$keep"; cp -r ./generated/ledger-v4 "$keep" 2>/dev/null \
    && echo "=== kept -> $keep ===" >> "$SUM"
  # The whole question, printed per arm: is the named test there, and does it bite?
  local n
  n=$(grep -rhoE "^func Test[A-Za-z0-9_]+" "$keep" --include="*_test.go" 2>/dev/null | sort -u | wc -l | tr -d ' ')
  local has="ABSENT"
  grep -rqE "func TestCreateTransactionMovesBalances\b" "$keep" 2>/dev/null && has="PRESENT"
  echo "ARM $name: testfuncs=$n  TestCreateTransactionMovesBalances=$has" >> "$SUM"
  # Teeth, not names: a test can be present and vacuous. Only a break can tell.
  ./_mutant_check.sh ledger "$keep" >> "$SUM" 2>&1
  case $? in
    0) echo "ARM $name: MUTANT CAUGHT — the suite has teeth" >> "$SUM" ;;
    1) echo "ARM $name: MUTANT MISSED — GREEN ON BROKEN CODE, hole open" >> "$SUM" ;;
    *) echo "ARM $name: mutant check ERRORED — result means nothing, read the log" >> "$SUM" ;;
  esac
}

run_arm A-oldspec-ruleoff "$OLD" ""
run_arm B-oldspec-ruleon  "$OLD" "completeness"
run_arm C-newspec-ruleoff "$NEW" ""

echo "########## 3-ARM COMPLETE ##########" >> "$SUM"
grep -hE "^(ARM |RESULT|COVERAGE)" "$SUM" > "${SUM}.summary"
cat "${SUM}.summary" >> "$SUM"
echo "summary -> ${SUM}.summary"
