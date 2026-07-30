#!/usr/bin/env bash
# THE FIRST ARM WITH AN UNCHANGED INPUT: the same HEAD spec, on a different server process.
#
# The machine rebooted at 09:20:52 on 30 July and took pid 4439 with it. Every control the
# ten-arm spec-edit series was graded against lived on that process. The standing rule says a
# restart makes a draw "a THIRD condition rather than a control" — adopted as a precaution and
# never once measured. This draw measures it, because a fresh control is mandatory now anyway
# and the comparison to the dead server's control is one extra grader call.
#
# See logs/PREREG-cross-server-control-replication.txt — prediction 65% identical, written first.
#
# The guard below is the same one _pristine_pre_edit_draw.sh uses, re-pinned to the NEW process.
# It is kept, not dropped, for the reason that script gives: a restart is invisible in every
# other check, because the port answers either way.
set -uo pipefail
cd "$(dirname "$0")"

SPEC="specs/taskflow.yaml"          # UNMODIFIED at HEAD. No variant, deliberately.
CONTROL="./generated/taskflow-chain6"
OUT="./generated/taskflow-xserver"
WANT_PID=2212
WANT_START="Thu Jul 30 09:29:30 2026"

# ---- the premise, VERIFIED rather than assumed --------------------------------------------
PID=$(lsof -ti:8080 2>/dev/null | head -1)
if [[ -z "$PID" ]]; then
  echo "REFUSING: nothing is listening on :8080."
  exit 4
fi
START=$(ps -o lstart= -p "$PID" 2>/dev/null | sed 's/^ *//; s/ *$//')
if [[ "$PID" != "$WANT_PID" || "$START" != "$WANT_START" ]]; then
  echo "REFUSING: :8080 is not the process this draw is pinned to."
  echo "  want pid=$WANT_PID start='$WANT_START'"
  echo "  have pid=$PID start='$START'"
  echo "A draw on a third process answers a question nobody asked. Re-pin deliberately."
  exit 5
fi

# ---- the control must be a SNAPSHOT, or there is nothing to compare against ----------------
# _asdrawn_diff.py refuses a tree with no .pre-fix.json rather than silently comparing
# post-repair trees. Checking here too, so the failure costs zero GPU instead of sixteen minutes.
if [[ ! -f "$CONTROL/.pre-fix.json" ]]; then
  echo "REFUSING: control $CONTROL has no .pre-fix.json — post-repair trees are not draws."
  exit 6
fi

# ---- the spec must be the one the control was drawn from -----------------------------------
# If the working tree has drifted from HEAD, this stops being a pure server arm and becomes a
# spec edit nobody pre-registered. That is exactly the confound the series exists to avoid.
if ! git diff --quiet HEAD -- "$SPEC"; then
  echo "REFUSING: $SPEC differs from HEAD. This arm requires an UNCHANGED input."
  exit 7
fi

if pgrep -f "\.venv/bin/guildlm-build" > /dev/null; then
  echo "REFUSING: a draw is already in flight. Two draws share one GPU and neither is a control."
  exit 8
fi

rm -rf "$OUT"

LOG="logs/taskflow-xserver-$(date +%m%d%H%M).log"
echo "=== taskflow CROSS-SERVER control draw $(date) -> $OUT (log $LOG) ==="
echo "=== server pid=$PID start='$START' · spec=$SPEC UNMODIFIED · control=$CONTROL ==="
SECONDS=0
.venv/bin/guildlm-build main --spec "$SPEC" --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
RC=$?
echo "=== guildlm-build exit rc=$RC (${SECONDS}s) ==="

if [[ ! -f "$OUT/.pre-fix.json" ]]; then
  echo
  echo "VERDICT: UNMEASURED — the draw produced no snapshot. This says NOTHING about the"
  echo "server; it says the machine never reached the question. Redraw. (Pre-registered branch.)"
  exit 3
fi

echo
echo "=== VERDICT: as-drawn, both sides from .pre-fix.json, file + function + residue ==="
echo "No --target: the input is byte-identical, so there is no file the edit was 'supposed'"
echo "to change. EVERY difference here is collateral of the process change alone."
.venv/bin/python _asdrawn_diff.py "$CONTROL" "$OUT"
echo
echo "IDENTICAL -> the process is inert at this resolution; the 4439 controls stay valid."
echo "DIFFERS   -> comparability is process-bound; every cross-DAY claim in the campaign is void."
