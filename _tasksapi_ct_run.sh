#!/usr/bin/env bash
# Regenerate tasks-api with the Content-Type test NAMED in the spec (f6a669e), so the
# closure can be graded against the before-table. Written as a script rather than typed
# because the previous attempt was cut by hand mid-round and left no record of how it
# had been launched — a run whose invocation is not written down cannot be re-run.
#
# Base 7B first, go-dev-final as the escalation member: the same shape the earlier
# tasks-api greens used (0-2 escalations), and the shadow-t gate landed since
# (120bb7c), which is what unlocked the 3381s compile deadlock this run hit before.
set -uo pipefail
cd "$(dirname "$0")"
OUT="./generated/tasksapi-ct"
rm -rf "$OUT"
LOG="logs/tasksapi-ct-$(date +%m%d%H%M).log"
echo "=== tasks-api Content-Type closure run -> $OUT (log $LOG) ==="

SECONDS=0
.venv/bin/guildlm-build main --spec specs/tasks-api.yaml --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --fleet go-dev-final@http://localhost:8081/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
RC=$?
echo "=== guildlm-build exit rc=$RC (${SECONDS}s) ==="
tail -25 "$LOG"

MOD=$(find "$OUT" -name go.mod 2>/dev/null | head -1)
[[ -z "$MOD" ]] && { echo "RESULT tasks-api-ct: NO go.mod — generation failed early"; exit 0; }
cd "$(dirname "$MOD")" || exit 0
echo "=== INDEPENDENT verify ==="
go build ./... 2>&1 | tail -5; BR=${PIPESTATUS[0]}
go vet ./...   2>&1 | tail -5; VR=${PIPESTATUS[0]}
# -count=4: a single `go test` is a SAMPLE when map order is undefined (measured 25%
# catch at count=1 vs 68% at count=4 on the tasks-api sort flake).
go test -race -count=4 ./... 2>&1 | tail -20; TR=${PIPESTATUS[0]}
if [[ $BR -eq 0 && $VR -eq 0 && $TR -eq 0 ]]; then
  echo "RESULT tasks-api-ct: GREEN ✅"
else
  echo "RESULT tasks-api-ct: NOT-GREEN ❌ (build=$BR vet=$VR test=$TR)"
fi
