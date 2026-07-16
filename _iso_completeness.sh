#!/usr/bin/env bash
# Isolate the ONE open question about the completeness_rule: it PROVED itself on
# ratelimit (42.4 -> 75.4, 2/2) but workapi came back RED once with the rule and
# GREEN once without it — at IDENTICAL 80.5% coverage in both. Identical coverage
# means the rule did not change workapi's test SET at all, which is the opposite
# of what a rule-caused regression looks like: the suspect red was almost
# certainly the model writing TestListStoreError's assertion stochastically
# (`want nil` vs `errors.Is(errBoom)`). But that was n=1 on each side, and n=1
# cannot tell a cause from a coincidence. So: 3 runs per arm, count the reds.
#
# ALTERNATING arms on purpose (with, without, with, without, ...) rather than
# 3-then-3. Coverage on this suite has already moved ACROSS sessions with no code
# change (ratelimit 75.0 -> 42.4 on an unchanged builder), so the server is a
# drifting instrument. Blocking the arms would let any drift land entirely on one
# of them and masquerade as the rule's effect; alternating splits drift evenly.
#
# Usage: _iso_completeness.sh [reps]     (default 3)
set -uo pipefail
cd "$(dirname "$0")"
REPS="${1:-3}"
SUM="logs/iso-completeness-$(date +%m%d%H%M).log"
: > "$SUM"
echo "########## ISO completeness_rule: workapi with x$REPS vs without x$REPS (alternating) ##########" >> "$SUM"

for i in $(seq 1 "$REPS"); do
  for mode in with without; do
    if [[ "$mode" == "without" ]]; then
      export GUILDLM_NO_COMPLETENESS_RULE=1
    else
      unset GUILDLM_NO_COMPLETENESS_RULE
    fi
    echo "########## ARM=$mode REP=$i (GUILDLM_NO_COMPLETENESS_RULE=${GUILDLM_NO_COMPLETENESS_RULE:-unset}) ##########" >> "$SUM"
    ./_ab_run.sh workapi >> "$SUM" 2>&1
    # Keep EVERY artifact, green or red. The question is not just green/red, it is
    # WHICH test went red and what its assertion said — that only lives in the file.
    KEEP="./generated/_iso-workapi-${mode}-${i}"
    rm -rf "$KEEP"
    cp -r ./generated/workapi-v4 "$KEEP" 2>/dev/null && echo "=== kept artifact -> $KEEP ===" >> "$SUM"
    # The actual measurement: did the hard test go red, and how many test funcs
    # did the model write? Coverage alone hid this once already.
    TF=$(grep -rhoE "^func Test[A-Za-z0-9_]+" "$KEEP" --include="*_test.go" 2>/dev/null | sort -u | wc -l | tr -d ' ')
    echo "ISO $mode $i: testfuncs=$TF" >> "$SUM"
    grep -rhoE "^func Test[A-Za-z0-9_]+" "$KEEP" --include="*_test.go" 2>/dev/null | sort -u | sed "s/^/ISO $mode $i:   /" >> "$SUM"
  done
done

echo "########## ISO COMPLETE ##########" >> "$SUM"
# Read the file into memory BEFORE reopening it for append. `grep ... "$SUM" >>
# "$SUM"` streams: every line it appends becomes a line it then reads, and the
# file grows without bound — this one reached 16GB before I killed it. _sweep.sh
# survives the same shape only because `sort` buffers all input before writing.
# Do not rely on that accident; take the snapshot explicitly.
SUMMARY=$(grep -E "^(RESULT|COVERAGE|ISO) " "$SUM")
{ echo "=== ISO SUMMARY ==="; echo "$SUMMARY"; } >> "$SUM"
echo "SUMMARY LOG: $SUM"
