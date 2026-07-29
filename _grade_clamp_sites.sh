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

# site = file|text to break|replacement|OCCURRENCE index|the test that must notice
#
# THE OCCURRENCE INDEX IS NOT DECORATION, and its absence was a real defect in this script.
# `limit = h.defaultPageSize` appears TWICE in each handler — once for the parse-error path
# and once for the limit<=0 path:
#
#     54      limit = h.defaultPageSize      (strconv.Atoi failed)
#     57      limit = h.defaultPageSize      (limit <= 0)
#     60      limit = h.maxPageSize
#
# `sed 's|X|Y|'` replaces the first match ON EVERY LINE, so the original version of this
# script mutated BOTH sites while claiming to grade one. The verdict would have been
# well-formed and about something else — which is the third instance today of a grade that
# comes out clean and means nothing. Found by checking this script after discovering the
# same shape in workapi, where two character-identical writeJSON(w, StatusNotFound, nil)
# lines sit in different functions.
#
# So each site is graded on its OWN occurrence, and a target whose count does not match
# expectation makes the run REFUSE rather than guess. Same principle as the paging-seed gate
# design: refuse where the rewrite cannot be known correct.
SITES=(
  "internal/api/tasks.go|limit = h.defaultPageSize|limit = 7777|1|TestListDefaultsToTheConfiguredPageSize"
  "internal/api/tasks.go|limit = h.maxPageSize|limit = 7777|1|TestListCapsAtTheConfiguredMaxPageSize"
  "internal/api/projects.go|limit = h.defaultPageSize|limit = 7777|1|TestProjectListDefaultsToTheConfiguredPageSize"
  "internal/api/projects.go|limit = h.maxPageSize|limit = 7777|1|TestProjectListCapsAtTheConfiguredMaxPageSize"
)

# Replace only the Nth occurrence of a fixed string, counting line by line.
mutate_nth() {
  local file="$1" from="$2" to="$3" n="$4"
  awk -v FROM="$from" -v TO="$to" -v N="$n" '
    {
      if (index($0, FROM) > 0) {
        c++
        if (c == N) { sub(FROM, TO); }
      }
      print
    }' "$file" > "$file.tmp" && mv "$file.tmp" "$file"
}

echo "=== grading 4 clamp sites on $TREE (copy) $(date +%H:%M) ==="
printf '%-52s %-10s %-10s %s\n' "named test" "baseline" "mutant" "verdict"
caught=0; survived=0; incon=0
for s in "${SITES[@]}"; do
  IFS='|' read -r FILE FROM TO OCC TEST <<< "$s"
  rm -rf "$SCRATCH"; cp -R "$TREE" "$SCRATCH"

  # BASELINE FIRST — before touching anything.
  base=$(cd "$SCRATCH" && go test ./internal/api/ -run "^${TEST}\$" -count=1 2>&1)
  brc=$?
  if (( brc != 0 )); then
    printf '%-52s %-10s %-10s %s\n' "$TEST" "FAIL" "-" "INCONCLUSIVE (witness already broken)"
    incon=$((incon+1)); continue
  fi

  # Only now mutate, and only if the site is there AND unambiguous enough to index.
  HITS=$(grep -c "$FROM" "$SCRATCH/$FILE")
  if (( HITS == 0 )); then
    printf '%-52s %-10s %-10s %s\n' "$TEST" "PASS" "-" "SITE ABSENT ($FROM not in $FILE)"
    incon=$((incon+1)); continue
  fi
  if (( OCC > HITS )); then
    printf '%-52s %-10s %-10s %s\n' "$TEST" "PASS" "-" \
      "REFUSED: wanted occurrence $OCC, file has $HITS"
    incon=$((incon+1)); continue
  fi
  mutate_nth "$SCRATCH/$FILE" "$FROM" "$TO" "$OCC"
  # Prove exactly one site moved. A mutation that changed 0 or 2 lines is not the
  # mutation this row claims to grade, and its verdict would be well-formed and wrong.
  MOVED=$(diff <(grep -c "$FROM" "$TREE/$FILE") <(grep -c "$FROM" "$SCRATCH/$FILE") >/dev/null && echo 0 || echo $(( $(grep -c "$FROM" "$TREE/$FILE") - $(grep -c "$FROM" "$SCRATCH/$FILE") )))
  if (( MOVED != 1 )); then
    printf '%-52s %-10s %-10s %s\n' "$TEST" "PASS" "-" \
      "REFUSED: mutation changed $MOVED sites, expected exactly 1"
    incon=$((incon+1)); continue
  fi
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
