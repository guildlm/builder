#!/usr/bin/env bash
# Grade the four taskapipro field-clamp sites by mutation, on a COPY of the landed tree.
#
# Written BEFORE taskapipro-v5 landed, on purpose. A grader designed after seeing the result
# is a grader shaped to the result, and this one exists to test a prediction I registered at
# 90% (logs/PREDICTION-the-two-caught-clamp-sites-must-now-survive.txt): that all four sites
# now SURVIVE, including the two graded CAUGHT on chain4.
#
# THE BASELINE IS READ FIRST, AND THAT IS THE WHOLE POINT.
# Twin A cannot PASS — it seeds one item and asserts exactly 2 — so it is RED on the
# unmutated tree. A grader that only asks "did the named test fail after mutation?" would
# call that CAUGHT, when the test had already been failing and noticed nothing. _grade_scoped
# has been wrong on real data four times this campaign, and this is that failure shape
# exactly. So each site gets TWO runs:
#
#     baseline run (unmutated)   PASS   ->  mutant run FAIL = CAUGHT, PASS = SURVIVED
#     baseline run (unmutated)   FAIL   ->  INCONCLUSIVE. The witness was already broken;
#                                           nothing about the mutation can be learned from it.
#
# INCONCLUSIVE is a real verdict here and not a cop-out: it is the correct answer for a test
# that cannot pass, and reporting it as SURVIVED would overstate what was measured just as
# reporting it as CAUGHT would.
#
# NEVER MUTATE THE LANDED TREE. Everything happens in a scratch copy; generated/ is
# gitignored and a corrupted -v5 tree cannot be recovered.
set -uo pipefail
cd "$(dirname "$0")"

TREE="./generated/taskapipro-v5"
SCRATCH="/private/tmp/claude-501/-Users-fatihturker-Desktop-Personal-Dev-guildlm/4d8ebe11-b90f-4a12-93b4-80e8dc2d46c1/scratchpad/clampgrade"

if pgrep -f "\.venv/bin/guildlm-build" > /dev/null; then
  echo "REFUSING: a generation is in flight. A tree being written is not a tree to grade."
  exit 3
fi
if [[ ! -d "$TREE" ]]; then echo "REFUSING: $TREE missing"; exit 2; fi
if ! grep -qE "^RESULT taskapipro: " logs/sweep-v5-07290011.log 2>/dev/null; then
  echo "REFUSING: no RESULT line for taskapipro yet — the fix loop has not finished."
  echo "A mid-loop tree grades whatever round it happens to be in."
  exit 4
fi

# site  = file:the exact line to break:replacement:the test that is supposed to notice
SITES=(
  "internal/api/tasks.go|limit = h.defaultPageSize|limit = 7777|TestListDefaultsToTheConfiguredPageSize"
  "internal/api/tasks.go|limit = h.maxPageSize|limit = 7777|TestListCapsAtTheConfiguredMaxPageSize"
  "internal/api/projects.go|limit = h.defaultPageSize|limit = 7777|TestProjectListDefaultsToTheConfiguredPageSize"
  "internal/api/projects.go|limit = h.maxPageSize|limit = 7777|TestProjectListCapsAtTheConfiguredMaxPageSize"
)

echo "=== grading 4 clamp sites on $TREE (copy) $(date +%H:%M) ==="
printf '%-52s %-10s %-10s %s\n' "named test" "baseline" "mutant" "verdict"
caught=0; survived=0; incon=0
for s in "${SITES[@]}"; do
  IFS='|' read -r FILE FROM TO TEST <<< "$s"
  rm -rf "$SCRATCH"; cp -R "$TREE" "$SCRATCH"

  # BASELINE FIRST — before touching anything.
  base=$(cd "$SCRATCH" && go test ./internal/api/ -run "^${TEST}\$" -count=1 2>&1)
  brc=$?
  if (( brc != 0 )); then
    printf '%-52s %-10s %-10s %s\n' "$TEST" "FAIL" "-" "INCONCLUSIVE (witness already broken)"
    incon=$((incon+1)); continue
  fi

  # Only now mutate, and only if the line is actually there.
  if ! grep -q "$FROM" "$SCRATCH/$FILE"; then
    printf '%-52s %-10s %-10s %s\n' "$TEST" "PASS" "-" "SITE ABSENT ($FROM not in $FILE)"
    incon=$((incon+1)); continue
  fi
  sed -i '' "s|$FROM|$TO|" "$SCRATCH/$FILE"
  mut=$(cd "$SCRATCH" && go test ./internal/api/ -run "^${TEST}\$" -count=1 2>&1)
  mrc=$?
  if (( mrc != 0 )); then
    printf '%-52s %-10s %-10s %s\n' "$TEST" "PASS" "FAIL" "CAUGHT"
    caught=$((caught+1))
  else
    printf '%-52s %-10s %-10s %s\n' "$TEST" "PASS" "PASS" "SURVIVED"
    survived=$((survived+1))
  fi
done
rm -rf "$SCRATCH"

echo
echo "  CAUGHT $caught · SURVIVED $survived · INCONCLUSIVE $incon   (of 4)"
echo
echo "GRADING THE PREDICTION (logs/PREDICTION-the-two-caught-clamp-sites-must-now-survive.txt):"
echo "  it predicted all four SURVIVED at 90%, from _twin_witness saying 0 of 4 discriminate."
echo "  A CAUGHT row means the static instrument disagreed with mutation and the instrument"
echo "  is what needs re-examining, not the tree. An INCONCLUSIVE row means the prediction"
echo "  asked a question this tree cannot answer — which is itself the CANNOT-PASS result,"
echo "  and should be reported as such rather than folded into SURVIVED."
