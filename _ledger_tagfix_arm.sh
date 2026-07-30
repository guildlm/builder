#!/usr/bin/env bash
# LEDGER, NON-RENAME EDIT: does the split survive on a third spec, or is ledger just quiet?
#
# Pre-registered in logs/PREREG-ledger-inert-prose-swap.txt at 12:20, before this ran.
#
# The ledger name swap graded a CONFIRMED NULL. That is explained equally well by "name swaps are
# safe" and by "ledger is a stable spec, whatever you do to it" — every ledger observation is a
# single null. This arm separates them, and it is the symmetric twin of the arm that just ran.
#
#     PERTURBS -> "ledger is quiet" dies; the split survives on a third spec with BOTH edit kinds
#     NULL     -> the first exception to the 6-of-6 non-rename column, AND the best support the
#                 "quiet spec" reading could get. One arm cannot choose; the follow-up would be a
#                 THIRD ledger edit of a different kind.
#
# ONE DRAW. generated/ledger-ctl-proc3 already carries a 19-file snapshot from pid 42826 and the
# server is still 42826, so control and arm share a process — the only requirement. The 4439
# controls were abandoned because that PROCESS died, not because controls expire.
set -uo pipefail
cd "$(dirname "$0")"

CTL_SPEC="specs/ledger.yaml"
ARM_SPEC="specs/ledger-tagfix.yaml"
CTL_OUT="./generated/ledger-ctl-proc3"      # reused, already drawn
ARM_OUT="./generated/ledger-tagfix"
TARGET="internal/models/models.go"
WANT_PID=42826
WANT_START="Thu Jul 30 10:09:48 2026"

# NOT `lsof -ti:8080 | head -1` — colima's ssh forward also binds 8080. See _server_pid.sh.
PID=$(./_server_pid.sh) || exit 4
START=$(ps -o lstart= -p "$PID" 2>/dev/null | sed 's/^ *//; s/ *$//')
if [[ "$PID" != "$WANT_PID" || "$START" != "$WANT_START" ]]; then
  echo "REFUSING: :8080 is not the process the reused control was drawn on."
  echo "  want pid=$WANT_PID start='$WANT_START'"
  echo "  have pid=$PID start='$START'"
  echo "Reusing a control across a process boundary manufactures differences out of nothing —"
  echo "measured today at 3 to 6 CODE files from a byte-identical input. Redraw the control."
  exit 5
fi

[[ -f "$CTL_OUT/.pre-fix.json" ]] || { echo "REFUSING: $CTL_OUT has no snapshot."; exit 6; }

# The variant must be the control spec with exactly the one transposition applied, and nothing
# else. Re-derived here rather than trusted: _mkvariant_swap.py wrote it under an anagram guard,
# but nothing stops an editor touching it since.
# A REORDER cannot be undone by a substitution, so the guard is character-multiset identity:
# same bytes, same characters, different order. That is exactly what a block transposition is.
# This edit ADDS 16 characters, so the multiset guard does not apply. Guard instead that the
# variant is the control plus exactly the one phrase and nothing else.
if ! diff <(sed 's/`Account{ID string, Name string}`, with JSON tags./`Account{ID string, Name string}`./' "$ARM_SPEC") "$CTL_SPEC" > /dev/null; then
  echo "REFUSING: $ARM_SPEC is not $CTL_SPEC plus exactly the one phrase."; exit 7
fi


pgrep -f "\.venv/bin/guildlm-build" > /dev/null && { echo "REFUSING: a draw is in flight."; exit 8; }
[[ -e "$ARM_OUT" ]] && { echo "REFUSING: $ARM_OUT exists."; exit 9; }

LOG="logs/ledger-tagfix-$(date +%m%d%H%M).log"
echo "=== ledger TAG-FIX arm 6 $(date) -> $ARM_OUT (log $LOG) ==="
echo "=== pid=$PID · control=$CTL_OUT (reused) · target=$TARGET ==="
SECONDS=0
.venv/bin/guildlm-build main --spec "$ARM_SPEC" --out "$ARM_OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
echo "=== guildlm-build exit rc=$? (${SECONDS}s) ==="

[[ -f "$ARM_OUT/.pre-fix.json" ]] || { echo; echo "VERDICT: UNMEASURED — no snapshot. Redraw."; exit 3; }

echo
echo "=== VERDICT: as-drawn, both snapshots ==="
# No --rename: nothing is renamed. --target names the file the edit's own text lives in, so the
# tool can separate "the edit landed" from "the edit had collateral".
.venv/bin/python _asdrawn_diff.py "$CTL_OUT" "$ARM_OUT" --target="$TARGET"
echo
echo "⚠️ READ THE NULL-EDIT BRANCH FIRST. gofmt sorts imports, so an import-ORDER instruction may"
echo "   leave no trace at all. If $TARGET is identical AND nothing else moved, that is a null"
echo "   EDIT — the arm measured nothing — not a null RESULT. They are different claims."
