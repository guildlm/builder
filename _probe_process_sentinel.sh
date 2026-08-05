#!/usr/bin/env bash
# Classify a FRESH server process by what its models.go declares, for a fraction of a draw.
#
#     ./_probe_process_sentinel.sh [label]
#
# WHY THIS EXISTS. Both queued sentinel experiments are UNINFORMATIVE on a process whose declarer
# already writes ErrInsufficientFunds: the spec fix's gate cannot fire when nothing is missing,
# and the API-block endpoint passes whether or not the consumer can see the block, because the
# consumer's choice of the long name is 25 of 25 across a month. A fix for a defect can only be
# tested where the defect occurs, and which processes exhibit it is not knowable in advance:
#
#     pid  7598  ErrInsufficientFunds (7/7)   pid 49288  ErrInsufficient (2/2)
#     pid 86026  none at all          (2/2)   pid 77977  ErrInsufficientFunds (1)
#
# models.go is file 4 of 19 and costs ~8 minutes, against ~60 for a full draw. So: restart, draw
# until models.go lands, read it, kill.
#   logs/RESULT-the-killed-draw-answered-a-question-and-invalidated-both-experiments-designs.txt
#
# ⚠️⚠️ THE PROBE USES THE FULL SPEC AND IS KILLED, RATHER THAN USING A 4-FILE SPEC.
# This is the whole validity of the thing. `_file_list` renders EVERY file's path AND purpose
# into EVERY generation prompt (builder.py:1265), so a spec truncated to four files would give
# models.go a DIFFERENT prompt than the real draw does — and the probe would be classifying a
# process on an input the experiment will never use. Same spec, same prompt, stop early.
#
# ⚠️⚠️ THIS IS SELECTION AND THE LEDGER IS NOT OPTIONAL. Choosing a process by its baseline makes
# every downstream result CONDITIONAL: "among processes whose declarer gets the name wrong, does
# the fix help?" Every probe — kept AND discarded — is appended to logs/PROBE-LEDGER.txt. If only
# the kept ones were recorded, the conditional claim would silently read as an unconditional one,
# and the discarded probes are precisely the evidence that it is conditional.
# ⚠️ The probe must NEVER be used to re-estimate how often the defect occurs. The archive answers
# that (36% long / 36% abbreviated / 28% absent over 25 ledger trees). A rate computed from
# probes would be biased by exactly the ones this script throws away.
set -uo pipefail
cd "$(dirname "$0")"

LABEL="${1:-probe}"
PORT="${PORT:-8137}"
MODEL="mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
SPEC="specs/ledger-origorder.yaml"
EXAMPLES="examples/verified_contracts.jsonl"
OUT="./generated/probe-${LABEL}"
LOG="logs/probe-${LABEL}.log"
LEDGER="logs/PROBE-LEDGER.txt"
TARGET="internal/models/models.go"
TIMEOUT_S="${TIMEOUT_S:-1500}"

pgrep -f "\.venv/bin/guildlm-build" >/dev/null && { echo "REFUSING: a draw is in flight."; exit 8; }
[[ -e "$OUT" ]] && { echo "REFUSING: $OUT exists."; exit 9; }

echo "=== probe '$LABEL' · restarting the server to get a FRESH process ==="
PORT="$PORT" ./_server_restart.sh || { echo "REFUSING: server did not come up"; exit 3; }
PID=$(PORT="$PORT" ./_server_pid.sh) || { echo "REFUSING: cannot identify the server"; exit 4; }
echo "  probing server pid $PID on port $PORT"

GUILDLM_ENABLE_RULES="" .venv/bin/guildlm-build main --spec "$SPEC" --out "$OUT" \
  --model "$MODEL" --base-url "http://localhost:$PORT/v1" \
  --candidates 2 --examples "$EXAMPLES" --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1 &
DRAW=$!

# Wait for models.go, then stop. Poll on the FILE, not on a log line: the log announces a file
# BEFORE generating it, so acting on the announcement would read a file that is not there yet.
waited=0
while [[ $waited -lt $TIMEOUT_S ]]; do
  [[ -s "$OUT/$TARGET" ]] && break
  kill -0 "$DRAW" 2>/dev/null || { echo "  draw exited early (rc unknown) after ${waited}s"; break; }
  sleep 5; waited=$((waited+5))
done
sleep 3   # let the write settle; _write_file runs goimports before the content is final
kill "$DRAW" 2>/dev/null
wait "$DRAW" 2>/dev/null
echo "  draw stopped after ${waited}s"

if [[ ! -s "$OUT/$TARGET" ]]; then
  echo "  VERDICT: NO-FILE — models.go never landed in ${TIMEOUT_S}s"
  printf '%s  pid=%-7s label=%-16s VERDICT=NO-FILE\n' "$(date +%Y-%m-%dT%H:%M:%S)" "$PID" "$LABEL" >> "$LEDGER"
  exit 5
fi

# ⚠️ ON-DISK IS AS-DRAWN **ONLY** BECAUSE THE FIX LOOP NEVER RAN, AND THAT IS CHECKED, NOT ASSUMED.
# A post-repair tree read as a draw is the error behind every retraction on 29 July and two since.
if grep -qE "compile/test FAILED|fix round|deterministic fix|converged to green" "$LOG"; then
  echo "  REFUSING: repair activity in the log — this tree is NOT as-drawn"
  printf '%s  pid=%-7s label=%-16s VERDICT=VOID-REPAIRED\n' "$(date +%Y-%m-%dT%H:%M:%S)" "$PID" "$LABEL" >> "$LEDGER"
  exit 6
fi

# ⚠️ CALLS the classifier rather than inlining it. The first version had these six lines here
# and was "validated" against the four known trees by RE-TYPING them into a throwaway snippet —
# so what passed was a copy, free to drift from the original the moment either changed. The
# classifier now lives in _sentinel_verdict.py, has its own self-test, and is the same object
# this script runs.
VERDICT=$(.venv/bin/python ./_sentinel_verdict.py "$OUT/$TARGET") || {
  echo "  REFUSING: classifier failed on $OUT/$TARGET"
  printf '%s  pid=%-7s label=%-16s VERDICT=VOID-CLASSIFIER\n' "$(date +%Y-%m-%dT%H:%M:%S)" "$PID" "$LABEL" >> "$LEDGER"
  exit 7
}

printf '%s  pid=%-7s label=%-16s VERDICT=%s\n' "$(date +%Y-%m-%dT%H:%M:%S)" "$PID" "$LABEL" "$VERDICT" >> "$LEDGER"
echo "  VERDICT: $VERDICT   (server pid $PID)"
case "$VERDICT" in
  LONG) echo "  -> UNINFORMATIVE for both sentinel experiments. Discard and re-probe."
        echo "     (this probe IS in $LEDGER; discarded probes are the evidence the claim is conditional)"
        exit 1 ;;
  *)    echo "  -> INFORMATIVE. Run the paired experiment on pid $PID, and do not restart the server."
        exit 0 ;;
esac
