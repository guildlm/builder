#!/usr/bin/env bash
# A/B run of a spec against the mixed-v4 server (localhost:8080), then an
# INDEPENDENT go build/vet/test -race on the output to confirm green.
# Usage: _ab_run.sh <spec-name>   (e.g. taskapi, workapi)
set -uo pipefail
cd "$(dirname "$0")"
SPEC="${1:?usage: _ab_run.sh <spec>}"
OUT="./generated/${SPEC}-v4"
rm -rf "$OUT"
LOG="logs/ab-${SPEC}-v4-$(date +%m%d%H%M).log"
echo "=== A/B spec=$SPEC out=$OUT log=$LOG ==="

SECONDS=0
.venv/bin/guildlm-build main --spec "specs/${SPEC}.yaml" --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
RC=$?
echo "=== guildlm-build exit rc=$RC  (${SECONDS}s) ==="
tail -22 "$LOG"

MOD=$(find "$OUT" -name go.mod 2>/dev/null | head -1)
if [[ -z "$MOD" ]]; then
  echo "RESULT $SPEC: NO go.mod in $OUT — generation failed early"
  exit 0
fi
MODDIR=$(dirname "$MOD")
echo "=== INDEPENDENT verify in $MODDIR ==="
cd "$MODDIR" || exit 0
B=$(go build ./... 2>&1); BR=$?
V=$(go vet ./... 2>&1); VR=$?
T=$(go test -race ./... 2>&1); TR=$?
echo "-- build rc=$BR --"; echo "$B" | tail -4
echo "-- vet rc=$VR --";   echo "$V" | tail -4
echo "-- test rc=$TR --";  echo "$T" | tail -12
if [[ $BR -eq 0 && $VR -eq 0 && $TR -eq 0 ]]; then
  echo "RESULT $SPEC: GREEN ✅ (build+vet+test-race all pass)"
else
  echo "RESULT $SPEC: NOT-GREEN ❌ (build=$BR vet=$VR test=$TR)"
  # Archive the failure. Every run used to `rm -rf` the previous artifact, so a
  # broken project — the only hard evidence of what the model actually gets
  # wrong, and the thing every gate is verified against — survived only until
  # the next run of the same spec. That is how the middleware-wall artifact was
  # lost, and why the gate audit reported that gate as never firing. Failures
  # are the corpus; keep them.
  cd - >/dev/null || exit 0
  ARCHIVE="./generated/_fail-${SPEC}-$(date +%m%d%H%M%S)"
  cp -r "$OUT" "$ARCHIVE" 2>/dev/null && echo "=== archived failing artifact -> $ARCHIVE ==="
fi
