#!/usr/bin/env bash
# A/B run of a spec against the mixed-v4 server (localhost:8080), then an
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
OUT="./generated/${SPEC}-v4"
# NEVER DELETE A PREVIOUS DRAW — PRESERVE IT INSTEAD.
#
# _chain_run.sh states this rule and calls deleting a landed draw "the corpus-deletion shape
# with a smaller blast radius". This script — which BUILT THE ENTIRE -v4 CORPUS the capstone
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
# THE SUFFIX MATTERS: `-prevN` does not match the `*--v4` glob the sweeps and
# _provenance_census use, so a preserved tree is invisible to every consumer — the same
# property _redraw_taskapipro_once.sh relies on for its `-red-evidence` name.
if [[ -d "$OUT" ]]; then
  n=1
  while [[ -d "${OUT}-prev${n}" ]]; do n=$((n + 1)); done
  mv "$OUT" "${OUT}-prev${n}"
  echo "preserved previous draw -> ${OUT}-prev${n}  (not deleted; generated/ is gitignored)"
fi
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

# Coverage — the DEPTH of the green. A suite can be 100% green and still barely
# execute the code it shipped: the store packages sat at a flat 50.9% because the
# Task methods were tested and their mirrored Project twins were never called
# once. Green says "the tests that exist pass"; coverage says "the tests that
# exist reach the code". Report BOTH, and never trade one for the other —
# coverage bought by turning a spec red is not a gain.
#
# TWO metrics, because they answer different questions and mixing them silently
# manufactures progress. On the same taskapi artifact they disagree hard
# (models: 0.0% vs 25.0%; store: 50.9% vs 58.5%):
#   OWN  (go test -cover)      — does this package have tests OF ITS OWN?
#                                a package with no _test.go is 0%, by definition.
#   EXEC (-coverpkg=./...)     — is this code EXECUTED by any test in the module?
#                                models is 25% here purely because store/api tests
#                                construct models values while testing themselves.
# OWN is the one the specs move (add models_test.go, add the Project cases).
# EXEC is the one that says whether shipped code is dead. Print both, labelled.
if [[ $BR -eq 0 ]]; then
  # -count=1 (never the cache). The gate chain SHIFTS LINES when it inserts an
  # import, and a cached coverage row is keyed to the line numbers it was recorded
  # at. A merged -coverpkg profile then carries the SAME block twice — once at
  # 14.60,15.37 and again at 15.60,16.37, one line apart — so the denominator
  # counts every statement twice while the numerator counts it once. It reported
  # api at 58.5% while go itself said 69.0%, and it reported the whole coverage
  # push as a 5-point REGRESSION that had not happened. The line-shifting gates do
  # not only corrupt the files they repair; they poison the measurement downstream.
  echo "-- coverage OWN (go test -cover: package tested by its own tests) --"
  go test -count=1 -cover ./... 2>&1 | grep -E "coverage:" | sed 's/^/   /'

  PROF="/tmp/guildlm-cov-$$.out"
  go test -count=1 -coverpkg=./... -coverprofile="$PROF" ./... >/dev/null 2>&1
  if [[ -s "$PROF" ]]; then
    echo "-- coverage EXEC (-coverpkg=./...: code executed by ANY test) --"
    # DEDUPE BY BLOCK. Under -coverpkg=./... every test binary instruments every
    # package, so the merged profile lists each block once PER TEST BINARY: the
    # store binary reports store's blocks with count>0, the models binary reports
    # those SAME blocks with count=0. Summing the lines naively counts a block N
    # times in the denominator and once in the numerator — which reported store as
    # 55.3% EXEC while it was 100% OWN. EXEC is by definition a superset of OWN, so
    # that number was not a finding, it was a broken ruler. A block is covered if
    # ANY binary hit it; count it exactly once.
    awk 'NR>1 { stmt[$1]=$2; if ($3>0) hit[$1]=1 }
    END {
      for (k in stmt) {
        file=k; sub(/:.*/, "", file);
        i=length(file); while (i>0 && substr(file,i,1) != "/") i--;
        pkg=substr(file,1,i-1);
        tot[pkg]+=stmt[k]; T+=stmt[k];
        if (k in hit) { cov[pkg]+=stmt[k]; C+=stmt[k] }
      }
      for (p in tot) printf "   %6.1f%%  %s\n", 100*cov[p]/tot[p], p;
      printf "TOTAL_MARKER %.1f\n", (T>0 ? 100*C/T : 0);
    }' "$PROF" | sort -n | grep -v TOTAL_MARKER
    awk -v spec="$SPEC" 'NR>1 { stmt[$1]=$2; if ($3>0) hit[$1]=1 }
    END {
      for (k in stmt) { T+=stmt[k]; if (k in hit) C+=stmt[k] }
      printf "COVERAGE %s: %.1f%% exec-total\n", spec, (T>0 ? 100*C/T : 0)
    }' "$PROF"
    rm -f "$PROF"
  else
    echo "COVERAGE $SPEC: n/a (no profile)"
  fi
else
  echo "COVERAGE $SPEC: n/a (build failed)"
fi

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
