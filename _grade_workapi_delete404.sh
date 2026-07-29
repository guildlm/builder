#!/usr/bin/env bash
# Grade the workapi Delete-404 closure by mutation, FUNCTION-SCOPED, on a copy.
#
# Written before workapi-v5 landed a RESULT line, and built from the four ways a grade came
# out clean and meant nothing today. Each one is a guard here, not a comment:
#
#   1. BASELINE FIRST. A test that was already failing notices nothing, and a grader that
#      only asks "did it fail after mutation" calls that CAUGHT. Unlike taskapipro's Twin A
#      this test is EXPECTED to pass unmutated, so a red baseline means something else broke
#      and the grade is VOID rather than negative.
#
#   2. SCOPE TO THE FUNCTION. tasks.go holds TWO character-identical lines —
#      writeJSON(w, http.StatusNotFound, nil) inside Get, and the same inside Delete. A text
#      mutation hits both, or hits Get's and reports a verdict about Delete's. Get's 404 IS
#      exercised by TestGetTask, so the wrong-branch mutation returns SURVIVED: a false
#      negative indistinguishable from a broken closure.
#
#   3. PROVE EXACTLY ONE LINE MOVED. A mutation that changed 0 or 2 lines is not the
#      mutation being graded, whatever verdict follows it.
#
#   4. REFUSE, DO NOT GUESS. Unknown shape, missing site, ambiguous count -> INCONCLUSIVE.
#      Same principle as the paging-seed gate: refuse where the rewrite cannot be known
#      correct.
#
# The site moves between draws — it was tasks.go:91 as drawn and 93 after round 1, and its
# sentinel changed service.ErrNotFound -> store.ErrNotFound. So nothing here is addressed by
# line number.
set -uo pipefail
cd "$(dirname "$0")"

TREE="./generated/workapi-v5"
FILE="internal/api/tasks.go"
FUNC="func (h \*TaskHandler) Delete"
TEST="TestDeleteMissingReturns404"
FROM="writeJSON(w, http.StatusNotFound, nil)"
TO="writeJSON(w, http.StatusNoContent, nil)"   # the 404 branch stops answering 404
SCRATCH="/private/tmp/claude-501/-Users-fatihturker-Desktop-Personal-Dev-guildlm/4d8ebe11-b90f-4a12-93b4-80e8dc2d46c1/scratchpad/wa404"

if pgrep -f "\.venv/bin/guildlm-build" > /dev/null; then
  echo "REFUSING: a generation is in flight."; exit 3
fi
if ! grep -qE "^RESULT workapi: " logs/sweep-v5-07290011.log 2>/dev/null; then
  echo "REFUSING: no RESULT line for workapi — the fix loop has not finished."
  echo "A mid-loop tree grades whatever round it happens to be in."
  exit 4
fi
[[ -d "$TREE" ]] || { echo "REFUSING: $TREE missing"; exit 2; }

rm -rf "$SCRATCH"; cp -R "$TREE" "$SCRATCH"

# --- locate the function's line range, so the mutation cannot escape it ---
START=$(grep -nE "^${FUNC}" "$SCRATCH/$FILE" | head -1 | cut -d: -f1)
if [[ -z "$START" ]]; then
  echo "INCONCLUSIVE: '$FUNC' not found in $FILE — the handler moved or was renamed."
  exit 0
fi
# End at the next top-level func, or EOF.
END=$(awk -v s="$START" 'NR>s && /^func /{print NR-1; exit}' "$SCRATCH/$FILE")
[[ -z "$END" ]] && END=$(wc -l < "$SCRATCH/$FILE")
echo "Delete handler spans lines $START-$END of $FILE"

HITS=$(awk -v s="$START" -v e="$END" -v F="$FROM" 'NR>=s && NR<=e && index($0,F)>0 {c++} END{print c+0}' "$SCRATCH/$FILE")
TOTAL=$(grep -cF "$FROM" "$SCRATCH/$FILE")
echo "target appears $HITS time(s) inside Delete, $TOTAL time(s) in the whole file"
if (( HITS != 1 )); then
  echo "INCONCLUSIVE: expected exactly 1 occurrence inside Delete, found $HITS. Refusing to guess."
  exit 0
fi

# --- 1. BASELINE FIRST, before touching anything ---
BASE=$(cd "$SCRATCH" && go test ./internal/api/ -run "^${TEST}\$" -count=1 2>&1); BRC=$?
if (( BRC != 0 )); then
  echo
  echo "VOID — the unmutated baseline FAILS, so this tree cannot answer the question:"
  echo "$BASE" | tail -5
  echo
  echo "Delete-404 is expected green here (unlike taskapipro's Twin A, which could not pass"
  echo "by construction). A red baseline means something else in the tree broke."
  exit 0
fi
echo "baseline: PASS"

# --- 2+3. mutate ONLY inside the function, then prove exactly one line moved ---
awk -v s="$START" -v e="$END" -v F="$FROM" -v T="$TO" '
  NR>=s && NR<=e && index($0,F)>0 && !done { sub(F,T); done=1 }
  { print }' "$SCRATCH/$FILE" > "$SCRATCH/$FILE.tmp" && mv "$SCRATCH/$FILE.tmp" "$SCRATCH/$FILE"

MOVED=$(( TOTAL - $(grep -cF "$FROM" "$SCRATCH/$FILE") ))
if (( MOVED != 1 )); then
  echo "INCONCLUSIVE: mutation changed $MOVED line(s), expected exactly 1."
  exit 0
fi
echo "mutated exactly 1 line, inside Delete only"

MUT=$(cd "$SCRATCH" && go test ./internal/api/ -run "^${TEST}\$" -count=1 2>&1); MRC=$?
echo
if (( MRC != 0 )); then
  echo "VERDICT: CAUGHT — $TEST notices the Delete 404 branch being broken."
  echo "  The closure survived its own redraw AND still defends the line it was written for."
else
  echo "VERDICT: SURVIVED — the branch was broken and $TEST did not notice."
  echo "  That would retract the durability claim for this closure. Before believing it,"
  echo "  confirm the mutation landed inside Delete and not Get — see the line count above."
fi
rm -rf "$SCRATCH"
