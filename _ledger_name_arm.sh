#!/usr/bin/env bash
# THE THIRD-SPEC NAME SWAP: control and arm, both on ONE process, back to back.
#
# Pre-registered at 02:22 on 30 July as the next arm after the series closed. Under the split
# ("name swaps are a coin flip, every other edit kind perturbed 6 of 6") this should be ~50/50.
# Under the rival reading ("ratelimit is just a perturbable spec and taskflow's nulls were
# taskflow's") it should perturb. First arm all series where two live hypotheses disagree.
#
# ⚠️ DO NOT RUN THIS UNTIL THE CROSS-SERVER ARM HAS A VERDICT. If taskflow-xserver DIFFERS from
# chain6, the pre-committed follow-up is a THIRD taskflow draw, not this — because a difference
# there means the noise floor is unmeasured and a coin-flip arm cannot be read against it.
# See logs/PREREG-cross-server-control-replication.txt, the 09:37 amendment.
#
# TWO DRAWS, SEQUENTIAL, ONE LAUNCH. ledger has no snapshotted control on ANY process — none on 4439,
# none on 2212 either, which is why this arm cost two draws when it was first proposed. They run back to
# back rather than in parallel: two generations sharing one GPU is the CPU contention this repo
# has no guard for, and neither of them would be a control afterwards.
set -uo pipefail
cd "$(dirname "$0")"

CTL_SPEC="specs/ledger.yaml"
ARM_SPEC="specs/ledger-name1.yaml"
CTL_OUT="./generated/ledger-ctl-proc3"
ARM_OUT="./generated/ledger-name1"
TARGET="internal/service/service_test.go"
OLD=TestBalanceMissingAccount
NEW=TestBalanceAccountMissing
WANT_PID=42826
WANT_START="Thu Jul 30 10:09:48 2026"

PID=$(./_server_pid.sh) || exit 4   # NOT `lsof -ti:8080 | head -1`: see _server_pid.sh
START=$(ps -o lstart= -p "$PID" 2>/dev/null | sed 's/^ *//; s/ *$//')
if [[ "$PID" != "$WANT_PID" || "$START" != "$WANT_START" ]]; then
  echo "REFUSING: :8080 is not the process this arm is pinned to."
  echo "  want pid=$WANT_PID start='$WANT_START'"
  echo "  have pid=$PID start='$START'"
  echo "Control and arm MUST share one process — that is the only reason the ten closed arms"
  echo "survive the reboot at all. A control drawn on a different process is a third condition."
  exit 5
fi
if pgrep -f "\.venv/bin/guildlm-build" > /dev/null; then
  echo "REFUSING: a draw is already in flight."; exit 8
fi

# The variant is rebuilt-checked rather than trusted: _mkvariant_rename.py wrote it with a byte
# guard, but nothing stops an editor from having touched it since.
if ! diff <(sed "s/$NEW/$OLD/" "$ARM_SPEC") "$CTL_SPEC" > /dev/null; then
  echo "REFUSING: $ARM_SPEC is not $CTL_SPEC with exactly the one rename applied."
  exit 6
fi
if [[ $(wc -c < "$CTL_SPEC") -ne $(wc -c < "$ARM_SPEC") ]]; then
  echo "REFUSING: byte counts differ; this is meant to be an equal-length swap."; exit 7
fi

draw () {  # $1 spec  $2 out  $3 label
  [[ -e "$2" ]] && { echo "REFUSING: $2 exists — an arm graded against a stale tree is undetectable."; return 9; }
  local log="logs/ledger-$3-$(date +%m%d%H%M).log"
  echo "=== ledger $3 draw $(date '+%H:%M:%S') · spec=$1 -> $2 (log $log) ==="
  SECONDS=0
  .venv/bin/guildlm-build main --spec "$1" --out "$2" \
    --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
    --base-url http://localhost:8080/v1 \
    --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
    --max-fix-rounds 5 > "$log" 2>&1
  echo "=== $3 exit rc=$? (${SECONDS}s) ==="
  [[ -f "$2/.pre-fix.json" ]] || { echo "!! $3 produced NO snapshot — UNMEASURED, not a null."; return 3; }
  return 0
}

draw "$CTL_SPEC" "$CTL_OUT" control || exit $?
draw "$ARM_SPEC" "$ARM_OUT" name1   || exit $?

echo
echo "=== VERDICT: as-drawn, both snapshots, rename neutralised ==="
# --rename is what makes this a measurement of COLLATERAL rather than of the edit itself. Without
# it every mention of the renamed test reads as a difference and the arm can only ever say "yes,
# the rename landed", which nobody asked.
.venv/bin/python _asdrawn_diff.py "$CTL_OUT" "$ARM_OUT" \
  --target="$TARGET" --rename="$OLD:$NEW"
echo
echo "⚠️ GREEN/NOT-GREEN IS NOT THE QUESTION AND NEVER WAS. ledger drew NOT-GREEN before (the"
echo "   spec asks for ErrInsufficientFunds, a draw wrote ErrInsufficient, six rounds never fixed"
echo "   it). As-drawn grading reads .pre-fix.json, which is what the MODEL WROTE — a compiler"
echo "   that never ran says nothing about it. A NOT-GREEN pair is still a gradable pair."
