#!/usr/bin/env bash
# The experiment the code queued for itself, now that its precondition is met.
#
# src/builder.py's _test_rule ends with: "WHAT WOULD EARN IT BACK, in order:
# (1) fix shortener's SPEC — it names no tests and never says to use Save's
# return...; (2) re-run shortener — if the break was the spec's, the cost
# disappears and the workapi gain stands alone."
#
# (1) is done: f8d9f4c ("shortener's spec named nothing and showed nothing: 2
# tests became 8"). The spec now NAMES 8 test functions, SHOWS the POST ->
# decode -> created.Code flow as 13 lines of code, and closes the second failure
# mode by name ("NEVER GUESS A SHORT CODE"). The fix reproduced independently in
# the 07-17 sweep: 72.4 -> 73.1.
#
# This is (2). The rule died of "a cost that reproduces and a benefit that does
# not" (173f4c7). Since then the benefit HAS reproduced, twice, independently:
#   ratelimit  0 effect      (2 processes, 7 arms)
#   workapi   +1 named test  (3/3, pre-gate)
#   ledger    +2 named tests (2026-07-17) — one with DEMONSTRATED TEETH: without
#             it a ledger that silently drops every credit ships GREEN.
# So only the cost is still standing, and it was measured against a spec that has
# since been fixed. If the cost was the spec's, it is gone. If it is the rule's,
# the rule stays off forever and the benefit must be bought some other way.
#
# ARMS ALTERNATE and share ONE server process. This project has been burned by
# comparing across processes — identical code measured 74.6 vs 75.0, and a +33
# "win" once belonged to a process's state rather than the model. Alternating
# also means a drift mid-run hits both arms, not one.
#
# Usage: _shortener_ab.sh [reps]   (default 2 per arm = 4 runs)
set -uo pipefail
cd "$(dirname "$0")"
REPS="${1:-2}"
SUM="logs/shortener-ab-$(date +%m%d%H%M).log"
: > "$SUM"
echo "########## shortener: completeness ON vs OFF — ${REPS} reps/arm, ONE process ##########" >> "$SUM"
echo "spec names $(grep -coE 'Test[A-Z][A-Za-z]+' specs/shortener.yaml) test-name mentions; shows a helper: $(grep -cE 'func (doReq|hit|newReq)' specs/shortener.yaml)" >> "$SUM"

run_arm () {                   # tag, rules
  local tag="$1" rules="$2" i="$3"
  echo "########## ARM ${tag} rep ${i} (rules='${rules:-none}') ##########" >> "$SUM"
  GUILDLM_ENABLE_RULES="$rules" ./_ab_run.sh shortener >> "$SUM" 2>&1
  local keep="./generated/_shortener-${tag}-${i}"
  rm -rf "$keep"; cp -r ./generated/shortener-v4 "$keep" 2>/dev/null \
    && echo "=== kept -> $keep ===" >> "$SUM"
  local n
  n=$(grep -rhoE "^func Test[A-Za-z0-9_]+" "$keep" --include="*_test.go" 2>/dev/null | sort -u | wc -l | tr -d ' ')
  # The rule's failure mode was never "too few tests" — it was inventing a helper
  # it then miscalled, and guessing a short code. Both leave fingerprints; look
  # for them by name rather than inferring them from a red.
  local invented
  invented=$(grep -rhoE "func (doReq|hit|newReq)\(" "$keep" --include="*_test.go" 2>/dev/null | sort -u | tr '\n' ' ')
  local guessed
  guessed=$(grep -rhc '"/r/0"' "$keep" --include="*_test.go" 2>/dev/null | paste -sd+ - | bc)
  echo "ARM ${tag} rep ${i}: testfuncs=${n} invented_helpers='${invented:-none}' guessed_code_hits=${guessed:-0}" >> "$SUM"
}

for i in $(seq 1 "$REPS"); do
  run_arm ON  "completeness" "$i"     # alternate, never all-ON-then-all-OFF
  run_arm OFF ""             "$i"
done

echo "########## SHORTENER A/B COMPLETE ##########" >> "$SUM"
grep -hE "^(ARM |RESULT|COVERAGE)" "$SUM" > "${SUM}.summary"
cat "${SUM}.summary" >> "$SUM"
echo "summary -> ${SUM}.summary"
