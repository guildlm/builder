#!/usr/bin/env bash
# Is taskapipro's red REAL, or is it the drift between two server processes?
#
# The sweep measured taskapipro 82.9 NOT-GREEN against an 84.3 GREEN baseline —
# but that baseline came from a DIFFERENT server process, and this project has
# already been burned once by exactly that: identical code measured 74.6 vs 75.0
# across processes, and a +33 "win" shipped one morning turned out to belong to a
# process's state, not the model. An A/B is only valid INSIDE one process.
#
# So: run the same spec N times against ONE server process and count the reds.
#   - red N/N  => deterministic; the spec (or the code) really does break here
#   - red k/N  => stochastic; the sweep's single red is a sample, not a regression
# Either way the 84.3 number stays out of the comparison — it is not commensurable.
#
# Every artifact is kept. The sweep's red was TestListLimit/TestListNegativeOffset
# "got [], want 1" — a test that builds a fresh store and never SEEDS it. Whether
# that same test fails the same way each rep is the whole question, and only the
# file can answer it; green/red alone cannot.
#
# A rerun used to `rm -rf` the artifacts of the run before it: KEEP was
# _iso-<spec>-<i>, so rep 1 of today overwrote rep 1 of the run whose conclusion
# I had already committed. The artifact IS the evidence — the guard's presence
# is only checkable by reading it — so an experiment that destroys the arm it is
# being compared against cannot be re-examined when the answer looks confirming.
# TAG separates the arms; default keeps the old name so nothing else breaks.
#
# Usage: _iso_taskapipro.sh [reps] [tag]   (default 2, untagged)
set -uo pipefail
cd "$(dirname "$0")"
SPEC=taskapipro
REPS="${1:-2}"
TAG="${2:-}"
SUM="logs/iso-${SPEC}-$(date +%m%d%H%M).log"
: > "$SUM"
echo "########## ISO $SPEC x$REPS — SAME server process (pid on 8080) ##########" >> "$SUM"
echo "named test funcs in spec: $(grep -coE 'Test[A-Z][A-Za-z]+:' "specs/${SPEC}.yaml")" >> "$SUM"

for i in $(seq 1 "$REPS"); do
  echo "########## REP=$i ##########" >> "$SUM"
  ./_ab_run.sh "$SPEC" >> "$SUM" 2>&1
  KEEP="./generated/_iso-${SPEC}${TAG:+-$TAG}-${i}"
  rm -rf "$KEEP"
  cp -r "./generated/${SPEC}-v4" "$KEEP" 2>/dev/null && echo "=== kept artifact -> $KEEP ===" >> "$SUM"
  TF=$(grep -rhoE "^func Test[A-Za-z0-9_]+" "$KEEP" --include="*_test.go" 2>/dev/null | sort -u | wc -l | tr -d ' ')
  echo "ISO rep $i: testfuncs=$TF" >> "$SUM"
  # The suspected defect, measured rather than assumed: does the List test seed
  # the store it lists from? Print the test body so the next reader sees it.
  grep -rhA12 "^func TestList\(Limit\|NegativeOffset\)" "$KEEP" --include="*_test.go" 2>/dev/null \
    | sed "s/^/ISO rep $i:   /" >> "$SUM"
done
echo "########## ISO COMPLETE ##########" >> "$SUM"
grep -hE "^(RESULT|COVERAGE|ISO rep [0-9]+: testfuncs)" "$SUM" > "${SUM}.summary"
cat "${SUM}.summary" >> "$SUM"
echo "summary -> ${SUM}.summary"
