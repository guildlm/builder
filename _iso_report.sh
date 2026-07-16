#!/usr/bin/env bash
# Read-only post-hoc analysis of the completeness_rule isolation. Separate file
# on purpose: bash reads a running script lazily by byte offset, so editing
# _iso_completeness.sh mid-run would corrupt the run it is measuring.
#
# Answers three questions IN ORDER. The order is the point:
#   1. Do the three WITH runs agree with EACH OTHER? Same code, same prompt, same
#      server process. If they disagree, generation is nondeterministic within a
#      session and NO 1-vs-1 arm comparison (nor any "2/2 repro") means anything.
#      Establish the noise floor BEFORE reading the signal.
#   2. What is the red rate per arm, and is it the SAME test going red?
#   3. Did the rule change the test SET (func count) — its actual claimed effect?
set -uo pipefail
cd "$(dirname "$0")"
TF="internal/service/service_test.go"

echo "=== 1. NOISE FLOOR: do same-arm runs agree with each other? ==="
for arm in with without; do
  for a in 1 2; do
    for b in $((a+1)) 3; do
      [[ $b -le 3 && $a -lt $b ]] || continue
      A="generated/_iso-workapi-${arm}-${a}"; B="generated/_iso-workapi-${arm}-${b}"
      [[ -d $A && -d $B ]] || continue
      # Compare only generated Go source; ignore go.sum ordering noise.
      D=$(diff -rq --exclude=go.sum "$A" "$B" 2>/dev/null | wc -l | tr -d ' ')
      TD=$(diff -q "$A/$TF" "$B/$TF" >/dev/null 2>&1 && echo same || echo DIFF)
      echo "  $arm $a vs $b: files_differing=$D   service_test.go=$TD"
    done
  done
done

echo
echo "=== 2. THE HARD TEST: TestListStoreError assertion form ==="
printf "  %-28s %-8s %-10s %s\n" ARTIFACT VERDICT ASSERTION TESTFUNCS
for arm in with without; do
  for i in 1 2 3; do
    D="generated/_iso-workapi-${arm}-${i}"; F="$D/$TF"
    [[ -d $D ]] || continue
    if [[ -f $F ]] && grep -q "func TestListStoreError" "$F"; then
      body=$(awk '/func TestListStoreError/,/^}/' "$F")
      if grep -q "errors.Is" <<<"$body"; then AS="errors.Is"; else AS="BOTCH"; fi
      grep -q "want nil" <<<"$body" && AS="BOTCH(want-nil)"
    else
      AS="ABSENT"   # dropped entirely — the completeness_rule's own failure mode
    fi
    N=$(grep -rhoE "^func Test[A-Za-z0-9_]+" "$D" --include="*_test.go" 2>/dev/null | sort -u | wc -l | tr -d ' ')
    # -count=1 -race, to match how RESULT was measured. Without -count=1 this
    # reads Go's TEST CACHE and reports a verdict no one re-ran; without -race a
    # deadlock or data race passes silently. A verdict from a stale cache is
    # worse than no verdict — it looks like a measurement.
    V=$( (cd "$D" && go test -count=1 -race ./... >/dev/null 2>&1) && echo GREEN || echo RED )
    printf "  %-28s %-8s %-10s %s\n" "$arm-$i" "$V" "$AS" "$N"
  done
done

echo
echo "=== 3. RECORDED RESULT/COVERAGE lines ==="
grep -hE "^(RESULT|COVERAGE|ISO ) " logs/iso-completeness-*.log 2>/dev/null | tail -30
