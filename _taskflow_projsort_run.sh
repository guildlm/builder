#!/usr/bin/env bash
# taskflow closure #12: does correcting the file's own test COUNT produce the seventh test?
# Waits for the corpus rebuild to finish first — one generation at a time on the GPU, and
# never a heavy job alongside a live build (that rule cost a run earlier today).
#
# Graded on the MUTATION, not the name: reversing ListProjects alone must flip
# SURVIVED -> CAUGHT. See logs/PREDICTION-taskflow-the-file-counted-six.txt.
set -uo pipefail
cd "$(dirname "$0")"

while pgrep -f "_sweep.sh|_rebuild_corpus.sh|guildlm-build main" > /dev/null; do sleep 60; done
echo "=== queue clear; taskflow projects-sort closure run $(date) ==="

OUT="./generated/taskflow-projsort"
rm -rf "$OUT"
LOG="logs/taskflow-projsort-$(date +%m%d%H%M).log"
SECONDS=0
.venv/bin/guildlm-build main --spec specs/taskflow.yaml --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --fleet go-dev-final@http://localhost:8081/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
echo "=== guildlm-build exit rc=$? (${SECONDS}s) ==="
tail -20 "$LOG"

MOD=$(find "$OUT" -name go.mod 2>/dev/null | head -1)
[[ -z "$MOD" ]] && { echo "RESULT taskflow-projsort: NO go.mod — generation failed early"; exit 0; }
cd "$(dirname "$MOD")" || exit 0
go build ./... 2>&1 | tail -3; BR=${PIPESTATUS[0]}
go vet ./...   2>&1 | tail -3; VR=${PIPESTATUS[0]}
go test -race -count=4 ./... 2>&1 | tail -12; TR=${PIPESTATUS[0]}
if [[ $BR -eq 0 && $VR -eq 0 && $TR -eq 0 ]]; then
  echo "RESULT taskflow-projsort: GREEN ✅"
else
  echo "RESULT taskflow-projsort: NOT-GREEN ❌ (build=$BR vet=$VR test=$TR)"
fi
cd - > /dev/null
echo "=== named tests written ==="
grep -h "^func Test" "$OUT"/*_test.go | sed 's/^func //;s/(.*//' | sort
