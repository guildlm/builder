#!/usr/bin/env bash
# THE FLOOR DRAW: the same spec, the same process, nothing changed at all.
#
# The cross-server arm came back DIFFERS — 4 files and 3 functions of different PROGRAM from a
# byte-identical input. Two readings fit it equally, and the pre-committed follow-up (written at
# 09:37, before the verdict, in PREREG-cross-server-control-replication.txt) is this draw:
#
#   (a) CROSS-PROCESS drift. The server process is a condition, as open question #3 suspects.
#   (b) THE PIPELINE IS NOT DETERMINISTIC AT ALL, and the premise that a fixed condition
#       reproduces byte-for-byte was never directly measured — only inferred from two DIFFERENT
#       specs agreeing where their prompts agreed (name5 vs chain6, 15 of 16 files).
#
# Same spec, same process, same everything:
#   identical -> within-process determinism confirmed DIRECTLY. The chain6 difference is then
#                genuinely cross-process and (a) stands.
#   differs   -> (b), and it is far larger than (a): every "perturbed" verdict in the ten-arm
#                distribution was read against a noise floor nobody ever took, and the series
#                needs that floor before any of it means what it says.
#
# This draw is graded against BOTH prior draws, which costs one extra grader call and nothing
# else. xserver-vs-this is the floor. chain6-vs-this is a second cross-process sample, and if the
# floor turns out to be non-zero it is the only way to tell "cross-process is BIGGER than the
# floor" from "cross-process is just the floor showing up twice".
set -uo pipefail
cd "$(dirname "$0")"

SPEC="specs/taskflow.yaml"          # UNMODIFIED at HEAD. Same input as xserver and chain6.
FLOOR="./generated/taskflow-xserver"   # same process, same spec  -> the floor
XSERV="./generated/taskflow-chain6"    # different process, same spec -> the cross-process pair
OUT="./generated/taskflow-xserver2"
WANT_PID=2212
WANT_START="Thu Jul 30 09:29:30 2026"

PID=$(lsof -ti:8080 2>/dev/null | head -1)
[[ -z "$PID" ]] && { echo "REFUSING: nothing is listening on :8080."; exit 4; }
START=$(ps -o lstart= -p "$PID" 2>/dev/null | sed 's/^ *//; s/ *$//')
if [[ "$PID" != "$WANT_PID" || "$START" != "$WANT_START" ]]; then
  echo "REFUSING: :8080 is not the process this draw is pinned to."
  echo "  want pid=$WANT_PID start='$WANT_START'"
  echo "  have pid=$PID start='$START'"
  echo "THE WHOLE POINT of this draw is SAME PROCESS. On a different one it measures nothing"
  echo "that xserver did not already measure, and it would look exactly like a result."
  exit 5
fi
for t in "$FLOOR" "$XSERV"; do
  [[ -f "$t/.pre-fix.json" ]] || { echo "REFUSING: $t has no .pre-fix.json."; exit 6; }
done
if ! git diff --quiet HEAD -- "$SPEC"; then
  echo "REFUSING: $SPEC differs from HEAD. This arm requires an UNCHANGED input."; exit 7
fi
if pgrep -f "\.venv/bin/guildlm-build" > /dev/null; then
  echo "REFUSING: a draw is already in flight."; exit 8
fi
[[ -e "$OUT" ]] && { echo "REFUSING: $OUT exists."; exit 9; }

LOG="logs/taskflow-xserver2-$(date +%m%d%H%M).log"
echo "=== taskflow WITHIN-SERVER floor draw $(date) -> $OUT (log $LOG) ==="
echo "=== server pid=$PID start='$START' · spec=$SPEC UNMODIFIED ==="
SECONDS=0
.venv/bin/guildlm-build main --spec "$SPEC" --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
echo "=== guildlm-build exit rc=$? (${SECONDS}s) ==="

[[ -f "$OUT/.pre-fix.json" ]] || { echo; echo "VERDICT: UNMEASURED — no snapshot. Redraw."; exit 3; }

echo
echo "############ THE FLOOR: same process, same spec (xserver vs xserver2) ############"
.venv/bin/python _asdrawn_diff.py "$FLOOR" "$OUT"
echo
echo "############ CROSS-PROCESS, second sample (chain6 vs xserver2) ############"
.venv/bin/python _asdrawn_diff.py "$XSERV" "$OUT"
echo
echo "READ THE FLOOR FIRST. If it is IDENTICAL, the pipeline is deterministic within a process"
echo "and the chain6 differences are cross-process. If it DIFFERS, the pipeline is simply"
echo "nondeterministic, the server hypothesis is unnecessary, and the ten-arm distribution was"
echo "measured against a floor nobody had taken."
