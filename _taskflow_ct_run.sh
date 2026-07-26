#!/usr/bin/env bash
# Regenerate taskflow with its Content-Type test NAMED rather than appended (11dad1a).
# Same launch shape as the tasks-api closure run, written down for the same reason: a
# run whose invocation is not in the repo cannot be re-run, and taskflow is the spec
# that needs SEVERAL runs before either claim is measurable.
set -uo pipefail
cd "$(dirname "$0")"
OUT="./generated/taskflow-ct"
rm -rf "$OUT"
LOG="logs/taskflow-ct-$(date +%m%d%H%M).log"
echo "=== taskflow Content-Type naming run -> $OUT (log $LOG) ==="

SECONDS=0
.venv/bin/guildlm-build main --spec specs/taskflow.yaml --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --fleet go-dev-final@http://localhost:8081/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
RC=$?
echo "=== guildlm-build exit rc=$RC (${SECONDS}s) ==="
grep -cE "fix round" "$LOG" | sed 's/^/fix-round lines: /'
grep -c "escalat" "$LOG" | sed 's/^/escalation lines: /'
tail -25 "$LOG"

MOD=$(find "$OUT" -name go.mod 2>/dev/null | head -1)
[[ -z "$MOD" ]] && { echo "RESULT taskflow-ct: NO go.mod — generation failed early"; exit 0; }
cd "$(dirname "$MOD")" || exit 0
echo "=== INDEPENDENT verify ==="
go build ./... 2>&1 | tail -5; BR=${PIPESTATUS[0]}
go vet ./...   2>&1 | tail -5; VR=${PIPESTATUS[0]}
go test -race -count=4 ./... 2>&1 | tail -20; TR=${PIPESTATUS[0]}
if [[ $BR -eq 0 && $VR -eq 0 && $TR -eq 0 ]]; then
  echo "RESULT taskflow-ct: GREEN ✅"
else
  echo "RESULT taskflow-ct: NOT-GREEN ❌ (build=$BR vet=$VR test=$TR)"
fi
