#!/usr/bin/env bash
# Regenerate bitset with the out-of-range guard witnessed AT the boundary (index 128)
# instead of comfortably past it (index 200).
#
# A SEPARATE SCRIPT rather than another entry in _chain_sweep.sh, because that sweep is
# running: editing a script a live loop re-executes each iteration is the same class of
# mistake as running a destructive command against a live build. Waits for the GPU the
# same way.
#
# Identical flags to _ab_run.sh — the conditions the -v4 tree was built under.
set -uo pipefail
cd "$(dirname "$0")"

# MATCH THE EXECUTABLE, NOT A STRING ANY COMMAND LINE CAN CONTAIN. `pgrep -f
# "guildlm-build main"` also matches every shell whose own command line mentions it —
# including the `until ! pgrep -f "guildlm-build main"; do sleep; done` waiters this
# repo writes constantly. Two orphaned waiters of mine matched their own pattern and
# made _resweep_v4 refuse on a machine with nothing generating. The guard was right
# about its query and wrong about the world, which is the failure this whole session
# has been about. `.venv/bin/guildlm-build` is the path only the real process carries.
while pgrep -f "\.venv/bin/guildlm-build" > /dev/null; do sleep 30; done
echo "=== GPU free; bitset witness run $(date) ==="

OUT="./generated/bitset-witness"
rm -rf "$OUT"
LOG="logs/bitset-witness-$(date +%m%d%H%M).log"
SECONDS=0
.venv/bin/guildlm-build main --spec specs/bitset.yaml --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
RC=$?
echo "=== guildlm-build exit rc=$RC (${SECONDS}s) ==="
tail -18 "$LOG"

MOD=$(find "$OUT" -name go.mod 2>/dev/null | head -1)
[[ -z "$MOD" ]] && { echo "RESULT bitset-witness: NO go.mod — generation failed early"; exit 0; }
pushd "$(dirname "$MOD")" >/dev/null || exit 0
echo "=== INDEPENDENT verify ==="
go build ./... 2>&1 | tail -5; BR=${PIPESTATUS[0]}
go vet ./...   2>&1 | tail -5; VR=${PIPESTATUS[0]}
go test -race -count=4 ./... 2>&1 | tail -20; TR=${PIPESTATUS[0]}
if [[ $BR -eq 0 && $VR -eq 0 && $TR -eq 0 ]]; then
  echo "RESULT bitset-witness: GREEN ✅"
else
  echo "RESULT bitset-witness: NOT-GREEN ❌ (build=$BR vet=$VR test=$TR)"
fi
popd >/dev/null || exit 0

# The whole question is the NUMBER. A test named for the boundary that still writes 200
# is the failure this run exists to detect, and it looks green from every other angle.
echo "=== which witness did it use? ==="
grep -rn "Test(128)\|Clear(128)" "$OUT" 2>/dev/null | sed 's/^/  boundary: /' \
  || echo "  128 ABSENT — the witness did not move, the closure has not happened"
grep -rn "Test(200)\|Clear(200)" "$OUT" 2>/dev/null | sed 's/^/  far-out:  /'
grep -rn "func TestTestAtTheFirstIndexBeyond\|func TestClearAtTheFirstIndexBeyond" "$OUT" \
  2>/dev/null | sed 's/^/  named:    /' || echo "  neither named test was written"
