#!/usr/bin/env bash
# Regenerate taskflow with Chain given its OWN NAMED test (middleware_chain_test.go).
#
# SAME CONDITIONS AS THE TREE THAT SHOWED THE HOLE. taskflow-v4 came from _ab_run.sh
# against the BASE model at :8080 — no fleet — so this run uses those exact flags. The
# one claim being tested is "naming the invariant closes it"; a run that also changed
# the server would not be able to say which change did the work, and that is precisely
# the retraction that had to be made when a closure run's command was never written down.
#
# Writes to generated/taskflow-chain, NOT taskflow-v4: the -v4 tree is the tracked
# baseline behind logs/hole-hunt-rows.tsv, and overwriting it would destroy the SURVIVED
# row this run is trying to flip.
set -uo pipefail
cd "$(dirname "$0")"
OUT="./generated/taskflow-chain"
rm -rf "$OUT"
LOG="logs/taskflow-chain-$(date +%m%d%H%M).log"
echo "=== taskflow Chain naming run -> $OUT (log $LOG) ==="

SECONDS=0
.venv/bin/guildlm-build main --spec specs/taskflow.yaml --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
RC=$?
echo "=== guildlm-build exit rc=$RC (${SECONDS}s) ==="
tail -22 "$LOG"

MOD=$(find "$OUT" -name go.mod 2>/dev/null | head -1)
[[ -z "$MOD" ]] && { echo "RESULT taskflow-chain: NO go.mod — generation failed early"; exit 0; }
cd "$(dirname "$MOD")" || exit 0
echo "=== INDEPENDENT verify ==="
go build ./... 2>&1 | tail -5; BR=${PIPESTATUS[0]}
go vet ./...   2>&1 | tail -5; VR=${PIPESTATUS[0]}
go test -race -count=4 ./... 2>&1 | tail -20; TR=${PIPESTATUS[0]}
if [[ $BR -eq 0 && $VR -eq 0 && $TR -eq 0 ]]; then
  echo "RESULT taskflow-chain: GREEN ✅"
else
  echo "RESULT taskflow-chain: NOT-GREEN ❌ (build=$BR vet=$VR test=$TR)"
fi
echo "=== was the Chain test written, and does it assert the ORDER? ==="
grep -l "TestChainAppliesEveryMiddlewareOutermostFirst" ./*_test.go 2>/dev/null \
  || echo "  NOT WRITTEN — the naming did not take"
grep -n "first,second,handler" ./*_test.go 2>/dev/null \
  || echo "  order string absent — a test exists but may assert something weaker"
