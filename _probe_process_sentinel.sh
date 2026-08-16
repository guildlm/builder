#!/usr/bin/env bash
# Classify a FRESH server process by what its models.go declares, for a fraction of a draw.
#
#     ./_probe_process_sentinel.sh [label]                                    # fresh process, baseline
#     RESTART=0 ROLE=treated SPEC=<other> ./_probe_process_sentinel.sh [label]  # the paired arm
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

# ⚠️ SPEC AND RESTART ARE PARAMETERS BECAUSE THE PAIRED DESIGN NEEDS BOTH, and on 5 August it
# had neither: the four draws of the first pair were issued by hand because this script always
# restarted and always used one spec. That worked, and it is exactly the shape this campaign has
# a standing rule against — the protocol that ran was not the protocol that is committed.
#
#   SPEC=...     which spec to draw. There are now TWO and a verdict without one is meaningless.
#                Both go in the ledger line for that reason.
#   RESTART=0    reuse the RUNNING server. This is what makes a pair a pair: baseline and treated
#                must be drawn by the SAME process, because 31 July established that the
#                declaration under test varies BY PROCESS. Restarting between the arms would
#                confound the treatment with the thing it is being compared against.
LABEL="${1:-probe}"
PORT="${PORT:-8137}"
MODEL="mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
SPEC="${SPEC:-}"
RESTART="${RESTART:-1}"
ROLE="${ROLE:-baseline}"
EXAMPLES="examples/verified_contracts.jsonl"
OUT="./generated/probe-${LABEL}"
LOG="logs/probe-${LABEL}.log"
LEDGER="logs/PROBE-LEDGER.txt"
TARGET="internal/models/models.go"
TIMEOUT_S="${TIMEOUT_S:-1500}"

# ⚠️ ONE RECORDER, CALLED ON EVERY EXIT PATH. There were four copies of this printf, and the spec
# field would have had to be added to all four; a ledger that records the spec on the success path
# and forgets it on the void paths is worse than one that never had the field, because the rows
# that look complete are the ones you would trust.
record () {   # record <verdict>
  printf '%s  pid=%-7s label=%-18s spec=%-28s VERDICT=%s\n' \
    "$(date +%Y-%m-%dT%H:%M:%S)" "$PID" "$LABEL" "$(basename "$SPEC")" "$1" >> "$LEDGER"
}

pgrep -f "\.venv/bin/guildlm-build" >/dev/null && { echo "REFUSING: a draw is in flight."; exit 8; }
[[ -e "$OUT" ]] && { echo "REFUSING: $OUT exists."; exit 9; }

# ⚠️⚠️ SPEC HAS NO DEFAULT, AND THAT IS A FIX. It used to default to specs/ledger-origorder.yaml
# — the TREATED spec, the one carrying the shipped `var ErrX` phrasing. On 10 August three
# baseline probes were run without SPEC set and all three came back LONG, which is precisely what
# the treated spec is supposed to do: they classified nothing about the processes and cost three
# restarts. A default that silently answers a DIFFERENT question than the caller asked is worse
# than no default, because the verdicts look valid. The ledger's spec column caught it.
[[ -n "$SPEC" ]] || { echo "REFUSING: set SPEC explicitly — there is no safe default. Baseline is specs/ledger-origorder-baseline.yaml"; exit 10; }
[[ -s "$SPEC" ]] || { echo "REFUSING: no spec at $SPEC"; exit 10; }

if [[ "$RESTART" == "1" ]]; then
  echo "=== probe '$LABEL' · spec $SPEC · restarting the server to get a FRESH process ==="
  PORT="$PORT" ./_server_restart.sh || { echo "REFUSING: server did not come up"; exit 3; }
else
  echo "=== probe '$LABEL' · spec $SPEC · REUSING the running process (paired arm) ==="
fi
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
  # ⚠️ "THE MODEL NEVER WROTE IT" AND "THE PROCESS UNDER TEST DIED" ARE NOT THE SAME ROW, and
  # until 16 August both were recorded as NO-FILE. That night pid 68231 was killed mid-arm by the
  # Metal driver (kIOGPUCommandBufferCallbackErrorImpactingInteractivity) and the ledger row for
  # that arm was indistinguishable from a slow draw — in a campaign whose every claim is
  # conditional on process identity, "the process is gone" is the single most important thing a
  # row can say. It is now its own verdict, and the runner aborts the series on it.
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "  VERDICT: VOID-SERVER-DIED — server pid $PID is gone; this arm classifies NOTHING"
    record VOID-SERVER-DIED
    exit 5
  fi
  # ⚠️ AND THE NUMBER IS THE ONE THAT HAPPENED. The old line printed ${TIMEOUT_S} unconditionally,
  # so an arm whose draw exited after 465s reported "never landed in 1500s" — a false number in a
  # log, which is the exact failure this repo has a standing rule against.
  echo "  VERDICT: NO-FILE — models.go never landed; gave up after ${waited}s (limit ${TIMEOUT_S}s)"
  record NO-FILE
  exit 5
fi

# ⚠️ ON-DISK IS AS-DRAWN **ONLY** BECAUSE THE FIX LOOP NEVER RAN, AND THAT IS CHECKED, NOT ASSUMED.
# A post-repair tree read as a draw is the error behind every retraction on 29 July and two since.
if grep -qE "compile/test FAILED|fix round|deterministic fix|converged to green" "$LOG"; then
  echo "  REFUSING: repair activity in the log — this tree is NOT as-drawn"
  record VOID-REPAIRED
  exit 6
fi

# ⚠️ CALLS the classifier rather than inlining it. The first version had these six lines here
# and was "validated" against the four known trees by RE-TYPING them into a throwaway snippet —
# so what passed was a copy, free to drift from the original the moment either changed. The
# classifier now lives in _sentinel_verdict.py, has its own self-test, and is the same object
# this script runs.
VERDICT=$(.venv/bin/python ./_sentinel_verdict.py "$OUT/$TARGET") || {
  echo "  REFUSING: classifier failed on $OUT/$TARGET"
  record VOID-CLASSIFIER
  exit 7
}

record "$VERDICT"
echo "  VERDICT: $VERDICT   (server pid $PID)"
# ⚠️ THE EXIT CODE ENCODES THE VERDICT (1 = LONG), NOT WHETHER THE PROBE WENT WELL — because
# "well" is opposite in the two arms. On the BASELINE arm LONG means the process has nothing
# wrong with it and must be discarded; on the TREATED arm LONG is the effect being tested for.
# The code stays the same in both so a caller can branch on it; only the advice differs, and
# printing the baseline advice after a treated probe is how a success gets thrown away.
case "$VERDICT:$ROLE" in
  LONG:baseline)
      echo "  -> UNINFORMATIVE for both sentinel experiments. Discard and re-probe."
      echo "     (this probe IS in $LEDGER; discarded probes are the evidence the claim is conditional)"
      exit 1 ;;
  LONG:*)
      echo "  -> the declarer wrote the spec's name on this arm."
      exit 1 ;;
  *:baseline)
      echo "  -> INFORMATIVE. Run the treated arm on pid $PID with RESTART=0, and do NOT restart."
      exit 0 ;;
  *)  echo "  -> the declarer did NOT write the spec's name on this arm."
      exit 0 ;;
esac
