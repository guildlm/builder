#!/usr/bin/env bash
# Live validation of 0fe717f (_canonical_toolchain_output).
#
# The unit test proves the regex. It does NOT prove the claim, which is about the
# whole pipeline: identical code => identical prompt => identical artifact, even
# when go's global test cache has been filled by earlier runs. The only way to
# show that is to run the thing three times back-to-back into a WARM cache — the
# exact condition under which the 6th run of the previous A/B diverged and went
# red — and diff the artifacts.
#
# BEFORE the fix: run 6 saw `ok pkg (cached)` where runs 1-5 saw `ok pkg 0.710s`,
# the fix prompt changed, and the run diverged.
# AFTER  the fix: that text never reaches the prompt, so all three must be
# byte-identical. If they are not, the cache was not the only contaminant and the
# story in 0fe717f is incomplete — which is worth knowing, and is the reason to
# run this rather than assume it.
set -uo pipefail
cd "$(dirname "$0")"
REPS="${1:-3}"
SUM="logs/cachefix-$(date +%m%d%H%M).log"
: > "$SUM"
echo "########## CACHEFIX VALIDATION: workapi x$REPS into a WARM go test cache ##########" >> "$SUM"

# Prove the cache is warm rather than hoping: a cold cache would make this test
# vacuous (no `(cached)` text => nothing for the fix to strip => three identical
# runs prove nothing about the fix).
WARM=$(cd generated/_iso-workapi-with-1 2>/dev/null && go test ./... 2>&1 | grep -c "cached")
echo "cache warm check: $WARM '(cached)' lines in a prior artifact" >> "$SUM"

for i in $(seq 1 "$REPS"); do
  echo "########## CACHEFIX REP=$i ##########" >> "$SUM"
  ./_ab_run.sh workapi >> "$SUM" 2>&1
  KEEP="./generated/_cachefix-workapi-$i"
  rm -rf "$KEEP"
  cp -r ./generated/workapi-v4 "$KEEP" 2>/dev/null && echo "=== kept -> $KEEP ===" >> "$SUM"
  # Did the run's toolchain output actually contain the contaminant? If the fix
  # works, `(cached)` appears in the LOG (go still prints it) but the artifacts
  # stay identical anyway — that pairing is the whole result.
  LOG=$(ls -t logs/ab-workapi-v4-*.log | head -1)
  echo "CACHEFIX $i: cached_lines_in_toolchain_output=$(grep -c 'cached' "$LOG")" >> "$SUM"
done

echo "=== CACHEFIX VERDICT ===" >> "$SUM"
for a in 1 2; do
  for b in $((a+1)) ; do
    [[ $b -le $REPS ]] || continue
    D=$(diff -rq --exclude=go.sum "generated/_cachefix-workapi-$a" "generated/_cachefix-workapi-$b" 2>/dev/null | wc -l | tr -d ' ')
    echo "CACHEFIX diff rep$a vs rep$b: files_differing=$D" >> "$SUM"
  done
done
[[ $REPS -ge 3 ]] && {
  D=$(diff -rq --exclude=go.sum generated/_cachefix-workapi-1 generated/_cachefix-workapi-3 2>/dev/null | wc -l | tr -d ' ')
  echo "CACHEFIX diff rep1 vs rep3: files_differing=$D" >> "$SUM"
}
# Snapshot before append — a plain `grep "$F" >> "$F"` streams its own output
# back in and never terminates. That mistake cost a 16GB log earlier today.
V=$(grep -E "^(RESULT|COVERAGE|CACHEFIX)" "$SUM")
{ echo "--- summary ---"; echo "$V"; } >> "$SUM"
echo "SUMMARY LOG: $SUM"
