#!/usr/bin/env bash
# Regenerate shortener with its two undefended 400/404 branches named.
#
# shortener is the second spec outside the Chain sweep (tasks-api was the first), which is
# why it can take an edit today without confounding the five-spec comparison.
#
# Two closures, both MIRRORS of a tested sibling: Shorten's third 400 case
# (url.ParseRequestURI) beside the two that have tests, and Stats' 404 beside Redirect's.
set -uo pipefail
cd "$(dirname "$0")"

while pgrep -f "guildlm-build main" > /dev/null; do sleep 30; done
echo "=== GPU free; shortener mirrors run $(date) ==="

OUT="./generated/shortener-mirrors"
n=2
while [[ -d "$OUT" ]]; do OUT="./generated/shortener-mirrors${n}"; n=$((n + 1)); done
rm -rf "$OUT"
LOG="logs/shortener-mirrors-$(date +%m%d%H%M).log"
SECONDS=0
.venv/bin/guildlm-build main --spec specs/shortener.yaml --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
echo "=== guildlm-build exit rc=$? (${SECONDS}s) ==="
tail -18 "$LOG"

MOD=$(find "$OUT" -name go.mod 2>/dev/null | head -1)
[[ -z "$MOD" ]] && { echo "RESULT shortener-mirrors: NO go.mod — generation failed early"; exit 0; }
pushd "$(dirname "$MOD")" >/dev/null || exit 0
echo "=== INDEPENDENT verify ==="
go build ./... 2>&1 | tail -5; BR=${PIPESTATUS[0]}
go vet ./...   2>&1 | tail -5; VR=${PIPESTATUS[0]}
go test -race -count=4 ./... 2>&1 | tail -20; TR=${PIPESTATUS[0]}
if [[ $BR -eq 0 && $VR -eq 0 && $TR -eq 0 ]]; then
  echo "RESULT shortener-mirrors: GREEN ✅"
else
  echo "RESULT shortener-mirrors: NOT-GREEN ❌ (build=$BR vet=$VR test=$TR)"
fi
popd >/dev/null || exit 0

echo "=== were both mirrors written? ==="
for t in TestShortenInvalidURL TestStatsMissing; do
  grep -rq "func $t" "$OUT" && echo "  $t: written" || echo "  $t: NOT WRITTEN"
done
