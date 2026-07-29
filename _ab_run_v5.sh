#!/usr/bin/env bash
# A/B run of a spec against the mixed-v5 server (localhost:8080), then an
# INDEPENDENT go build/vet/test -race on the output to confirm green.
# Usage: _ab_run.sh <spec-name>   (e.g. taskapi, workapi)
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
SPEC="${1:?usage: _ab_run.sh <spec>}"
OUT="./generated/${SPEC}-v5"
# NEVER DELETE A PREVIOUS DRAW — PRESERVE IT INSTEAD.
#
# _chain_run.sh states this rule and calls deleting a landed draw "the corpus-deletion shape
# with a smaller blast radius". This script — which BUILT THE ENTIRE -v5 CORPUS the capstone
# rests on — opened with an unconditional `rm -rf "$OUT"`. Re-running it on any spec destroyed
# that spec's tree, and generated/ is gitignored, so there was nothing to restore from.
#
# The repo already knew: _redraw_taskapipro_once.sh does `mv "$TREE" "$EVIDENCE"` by hand
# before calling this script, for exactly this reason. That workaround is now unnecessary and
# the protection is automatic.
#
# PRESERVED, NOT REFUSED, because the sweep runners call this in a loop and rely on being able
# to redraw. Refusing would break them; moving the old tree aside does not.
#
# THE SUFFIX MATTERS: `-prevN` does not match the `*--v5` glob the sweeps and
# _provenance_census use, so a preserved tree is invisible to every consumer — the same
# property _redraw_taskapipro_once.sh relies on for its `-red-evidence` name.
if [[ -d "$OUT" ]]; then
  n=1
  while [[ -d "${OUT}-prev${n}" ]]; do n=$((n + 1)); done
  mv "$OUT" "${OUT}-prev${n}"
  echo "preserved previous draw -> ${OUT}-prev${n}  (not deleted; generated/ is gitignored)"
fi
LOG="logs/ab-${SPEC}-v5-$(date +%m%d%H%M).log"
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
fi
