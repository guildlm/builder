#!/usr/bin/env bash
# Regenerate ONE spec with Chain given its own named test, and grade the result.
#
# The generalisation of _taskflow_chain_run.sh, kept because five specs describe the SAME
# Chain contract in the same words and grew the same undefended loop — which makes this an
# N=5 replication of one question ("does naming a boundary invariant close it?") rather
# than five separate anecdotes. Identical flags to _ab_run.sh, which is what built the -v4
# trees the SURVIVED rows were measured on: same model, same server, no fleet. Changing the
# spec AND the server in one run is how a closure claim becomes unattributable.
#
# Usage: _chain_run.sh <spec>          e.g. _chain_run.sh usersapi
set -uo pipefail
cd "$(dirname "$0")"
SPEC="${1:?usage: _chain_run.sh <spec>}"

# TWO BUILDS SHARE ONE GPU EXACTLY ONCE, and this script had no guard at all until 29 July.
#
# Every other runner in this repo refuses while a generation is in flight — _sweep_v5.sh,
# _sweep_v5_finish.sh, _sweep_v5_ledger.sh, _redraw_taskapipro_once.sh. This one, which is
# the script most likely to be run BY HAND in the middle of something else, did not. It sat
# in a written next-step queue ("./_chain_run.sh taskflow, after the sweep drains") where a
# single mistimed paste would have started a second guildlm-build beside a running sweep.
#
# Found by pre-flighting a queued step rather than by it going wrong, which is the only
# cheap way to find this class of thing.
#
# MATCH THE EXECUTABLE PATH, not a string a command line can contain: `pgrep -f
# "guildlm-build main"` also matches the shells that merely mention it, including this
# repo's own waiters, and that guard has already refused on a machine with nothing running.
if pgrep -f "\.venv/bin/guildlm-build" > /dev/null; then
  echo "REFUSING: a generation is in flight. Two builds share one GPU exactly once."
  echo "Wait for it to print its completion line, then re-run."
  exit 3
fi
# And refuse while a SCHEDULER is up, even between its jobs — a queue spends real minutes
# between generations running `go test -race`, and in that window no guildlm-build exists
# while the corpus is very much still being written. `grep -v "^$$ "` drops this process's
# own line; without it the guard matches itself, since _chain_run.sh is in the pattern.
_SCHED=$(pgrep -fl '_sweep_v5.*\.sh|_run_queue.*\.sh|_rebuild_corpus\.sh|_chain_run\.sh' | grep -v "^$$ " || true)
if [[ -n "$_SCHED" ]]; then
  echo "REFUSING: another scheduler is running — sequence these by hand, do not race them:"
  echo "$_SCHED" | sed 's/^/  /'
  exit 3
fi

# NEVER OVERWRITE A PREVIOUS DRAW. This script opens with `rm -rf "$OUT"`, generated/ is
# gitignored, and every landed draw is the evidence behind a graded RESULT — deleting one is
# the corpus-deletion shape with a smaller blast radius. Special-casing taskflow worked once
# and then taskapipro needed a second draw too, so the rule is general: find the first free
# name. n=2,3,... reads as the draw number, which is what the RESULT files call them.
OUT="./generated/${SPEC}-chain"
n=2
while [[ -d "$OUT" ]]; do
  OUT="./generated/${SPEC}-chain${n}"
  n=$((n + 1))
done
rm -rf "$OUT"
LOG="logs/${SPEC}-chain-$(date +%m%d%H%M).log"
echo "=== $SPEC Chain naming run -> $OUT (log $LOG) ==="

SECONDS=0
.venv/bin/guildlm-build main --spec "specs/${SPEC}.yaml" --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
RC=$?
echo "=== guildlm-build exit rc=$RC (${SECONDS}s) ==="
tail -18 "$LOG"

MOD=$(find "$OUT" -name go.mod 2>/dev/null | head -1)
[[ -z "$MOD" ]] && { echo "RESULT ${SPEC}-chain: NO go.mod — generation failed early"; exit 0; }
pushd "$(dirname "$MOD")" >/dev/null || exit 0
echo "=== INDEPENDENT verify ==="
go build ./... 2>&1 | tail -5; BR=${PIPESTATUS[0]}
go vet ./...   2>&1 | tail -5; VR=${PIPESTATUS[0]}
go test -race -count=4 ./... 2>&1 | tail -20; TR=${PIPESTATUS[0]}
if [[ $BR -eq 0 && $VR -eq 0 && $TR -eq 0 ]]; then
  echo "RESULT ${SPEC}-chain: GREEN ✅"
else
  echo "RESULT ${SPEC}-chain: NOT-GREEN ❌ (build=$BR vet=$VR test=$TR)"
fi
popd >/dev/null || exit 0

# TWO greps, not one. "The test exists" is the weaker claim and the one that was wrong
# twice today: a test function can survive a redraw while the assertion inside it
# evaporates. The order string is the assertion.
echo "=== was the Chain test written, and does it assert the ORDER? ==="
if grep -rl "TestChainAppliesEveryMiddlewareOutermostFirst" "$OUT" >/dev/null 2>&1; then
  grep -rl "TestChainAppliesEveryMiddlewareOutermostFirst" "$OUT" | sed 's/^/  named in: /'
else
  echo "  NOT WRITTEN — the naming did not take"
fi
grep -rn "first,second,handler" "$OUT" 2>/dev/null | sed 's/^/  asserts: /' \
  || echo "  order string ABSENT — a test may exist but assert something weaker"
