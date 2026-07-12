#!/usr/bin/env bash
# Sequentially A/B-run a list of specs against the mixed-v4 server and record a
# GREEN/NOT-GREEN line per spec. Used to certify regression-safety across the
# suite after adding gates/defaults, and to sweep new specs.
# Usage: _sweep.sh spec1 spec2 ...
set -uo pipefail
cd "$(dirname "$0")"
SUM="${GUILDLM_SWEEP_LOG:-logs/sweep-$(date +%m%d%H%M).log}"
: > "$SUM"
echo "########## SWEEP START: $* ##########" >> "$SUM"
for s in "$@"; do
  echo "########## SWEEP SPEC: $s ##########" >> "$SUM"
  ./_ab_run.sh "$s" >> "$SUM" 2>&1
done
echo "########## SWEEP COMPLETE ##########" >> "$SUM"
echo "=== SWEEP SUMMARY ===" >> "$SUM"
# Both numbers, side by side, on purpose. Green rate alone hid that the store
# packages were half-dead; coverage alone would let a red spec look healthy.
# Neither is the score. The pair is.
grep -E "^(RESULT|COVERAGE) " "$SUM" | sort >> "$SUM"
