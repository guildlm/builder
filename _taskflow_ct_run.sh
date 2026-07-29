#!/usr/bin/env bash
# Regenerate taskflow with its Content-Type test NAMED rather than appended (11dad1a).
# Same launch shape as the tasks-api closure run, written down for the same reason: a
# run whose invocation is not in the repo cannot be re-run, and taskflow is the spec
# that needs SEVERAL runs before either claim is measurable.
set -uo pipefail
cd "$(dirname "$0")"

# TWO BUILDS SHARE ONE GPU EXACTLY ONCE, and this runner had no guard until 29 July.
#
# It is one of six scripts that invoke guildlm-build DIRECTLY. Eleven more reach a generation
# THROUGH these six, so guarding here covers all seventeen — and eleven of those pass an env
# prefix (`GUILDLM_ENABLE_RULES=... ./_ab_run.sh ledger`), which is why a grep for a leading
# `./_ab_run.sh` missed them and the first count of "seven unguarded runners" was wrong.
#
# MATCH THE EXECUTABLE PATH, not a string a command line can contain. `pgrep -f
# "guildlm-build main"` also matches every shell that merely MENTIONS it, including the
# `until ! pgrep ...` waiters this repo writes constantly, and that mistake has already made
# a guard refuse on a machine with nothing running. `.venv/bin/guildlm-build` is the path
# only the real process carries.
if pgrep -f "\.venv/bin/guildlm-build" > /dev/null; then
  echo "REFUSING: a generation is in flight. Two builds share one GPU exactly once."
  echo "Wait for it to print its completion line, then re-run."
  exit 3
fi
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
