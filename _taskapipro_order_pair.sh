#!/usr/bin/env bash
# THE ORDER EXPERIMENT, PAIRED: draw A (original order), and draw B only if A actually STUBS.
#
# Pre-registered in logs/PREREG-stub-order-paired-experiment.txt.
#
# Arms 5 and 6 both failed the same way: the control did not exhibit the defect, so no fix could be
# shown to work. This script encodes the fix for that mistake — it REFUSES to draw B unless A stubs,
# so an uninformative pair costs one draw instead of two and is reported as a discard rather than
# discovered afterwards as a null.
set -uo pipefail
cd "$(dirname "$0")"

CTL_SPEC="specs/taskapipro-origorder.yaml"            # original order: store.go 6th, memory.go 7th
ARM_SPEC="specs/taskapipro.yaml"     # swapped:        memory.go 6th, store.go 7th
TAG="${1:?usage: _stub_order_pair.sh <tag>}"
A_OUT="./generated/taskapipro-pairA-$TAG"
B_OUT="./generated/taskapipro-pairB-$TAG"

PID=$(./_server_pid.sh) || exit 4
START=$(ps -o lstart= -p "$PID" 2>/dev/null | sed 's/^ *//; s/ *$//')
echo "=== stub-order pair '$TAG' · server pid=$PID start='$START' · $(date) ==="
# NOTE: no boot-string guard. kern.boottime's SEC field wobbles by a second under NTP discipline
# (observed 1785392452 -> 1785392451 with uptime continuous at 7:57), so pinning the FORMATTED
# string spuriously refuses. Both draws share one process, which is the condition that matters.

pgrep -f "\.venv/bin/guildlm-build" >/dev/null && { echo "REFUSING: a draw is in flight."; exit 8; }

draw () {  # $1 spec  $2 out  $3 label
  [[ -e "$2" ]] && { echo "REFUSING: $2 exists."; return 9; }
  local log="logs/taskapipro-pair$3-$TAG-$(date +%m%d%H%M).log"
  echo "--- draw $3: $1 -> $2 (log $log)"
  SECONDS=0
  .venv/bin/guildlm-build main --spec "$1" --out "$2" \
    --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
    --base-url http://localhost:8080/v1 \
    --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
    --max-fix-rounds 5 > "$log" 2>&1
  echo "--- $3 exit rc=$? (${SECONDS}s)"
  [[ -f "$2/.pre-fix.json" ]] || { echo "!! $3 produced NO snapshot — UNMEASURED."; return 3; }
}

stubbed () {  # as-drawn memory.go under 40 chars
  .venv/bin/python -c "
import json,sys
s=json.load(open('$1/.pre-fix.json'))
m=s.get('internal/store/memory.go','')
print(f'    memory.go as-drawn: {len(m)} chars')
sys.exit(0 if len(m.strip())<40 else 1)"
}

draw "$CTL_SPEC" "$A_OUT" A || exit $?
if stubbed "$A_OUT"; then
  echo "=== A STUBS -> the pair is INFORMATIVE. Drawing B (swapped order)."
else
  echo "=== A is FULL -> UNINFORMATIVE PAIR, as pre-registered (~1 process in 3)."
  echo "    Not drawing B: a fix cannot be shown to work on a case that is not broken."
  echo "    DISCARD. Restart the server and re-run for a new process."
  exit 0
fi

draw "$ARM_SPEC" "$B_OUT" B || exit $?
echo
echo "=== PAIR VERDICT ==="
if stubbed "$B_OUT"; then
  echo "  A STUBS · B STUBS -> ORDER DOES NOT FIX IT. Strong against the hypothesis, which says B"
  echo "  cannot stub because memory.go is written before store.go can take its job."
else
  echo "  A STUBS · B FULL  -> the order fixes it on this process. n=1; repeat for more pairs."
fi
echo
.venv/bin/python _asdrawn_diff.py "$A_OUT" "$B_OUT" --target=internal/store/memory.go
