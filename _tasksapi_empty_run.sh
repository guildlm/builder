#!/usr/bin/env bash
# Regenerate tasks-api with the EMPTY list case named and asserted on the raw body.
#
# tasks-api is the only spec with a pending closure that is NOT in the Chain sweep, which
# is why this one is being run and the other two empty-list closures (usersapi, taskapi)
# are held: the sweep's value is that five specs receive the SAME edit, and a second edit
# in one of them would make the comparison unreadable.
#
# Waits for the GPU. Identical flags to _ab_run.sh — the conditions the -v4 tree was built
# under, and the tree the SURVIVED verdict was measured on.
set -uo pipefail
cd "$(dirname "$0")"

while pgrep -f "guildlm-build main" > /dev/null; do sleep 30; done
echo "=== GPU free; tasks-api empty-list run $(date) ==="

OUT="./generated/tasksapi-empty"
# The first draw is a GRADED result (logs/RESULT-tasksapi-empty.txt): both closures held
# and it is the evidence for the Create-by-value spec contradiction. This script opens
# with `rm -rf "$OUT"`, generated/ is gitignored, and there is no way back — the same
# shape as the corpus deletion. A second draw takes its own name.
[[ -d ./generated/tasksapi-empty ]] && OUT="./generated/tasksapi-empty2"
rm -rf "$OUT"
LOG="logs/tasksapi-empty-$(date +%m%d%H%M).log"
SECONDS=0
.venv/bin/guildlm-build main --spec specs/tasks-api.yaml --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
RC=$?
echo "=== guildlm-build exit rc=$RC (${SECONDS}s) ==="
tail -18 "$LOG"

MOD=$(find "$OUT" -name go.mod 2>/dev/null | head -1)
[[ -z "$MOD" ]] && { echo "RESULT tasksapi-empty: NO go.mod — generation failed early"; exit 0; }
pushd "$(dirname "$MOD")" >/dev/null || exit 0
echo "=== INDEPENDENT verify ==="
go build ./... 2>&1 | tail -5; BR=${PIPESTATUS[0]}
go vet ./...   2>&1 | tail -5; VR=${PIPESTATUS[0]}
go test -race -count=4 ./... 2>&1 | tail -20; TR=${PIPESTATUS[0]}
if [[ $BR -eq 0 && $VR -eq 0 && $TR -eq 0 ]]; then
  echo "RESULT tasksapi-empty: GREEN ✅"
else
  echo "RESULT tasksapi-empty: NOT-GREEN ❌ (build=$BR vet=$VR test=$TR)"
fi
popd >/dev/null || exit 0

# Two things can go wrong and only one of them is visible from the test's NAME: the test
# can be written but populate the store first, which is what every other list test in the
# file does and therefore what the model is most likely to copy.
echo "=== was the empty case named, and is it actually empty? ==="
grep -rn "func TestListEmptyIsEmptyArray" -A12 "$OUT" 2>/dev/null \
  || echo "  NOT WRITTEN — the naming did not take"
