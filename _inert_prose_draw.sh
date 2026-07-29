#!/usr/bin/env bash
# The CONTROL ARM for the twelve-line import defect: same length, same place, inert content.
#
# THE QUESTION. 15e25f3 added twelve lines to taskapipro's PROJECTS entry and three
# implementation files lost their module prefix — `taskapipro/internal/models` instead of
# `guildlm.dev/taskapipro/internal/models`. Round-1 logs, four draws, two spec states:
#
#     chain4  PRE-edit   0 import errors      v5 (1st)  POST-edit  4
#     chain5  PRE-edit   0 import errors      v5 (2nd)  POST-edit  4
#
# Deterministic in both directions, server held fixed across the last three. What is NOT
# established is WHICH PROPERTY of those twelve lines does it. This draw adds twelve lines
# that are the same length, at the same insertion point, with the same indentation, and say
# nothing about handlers, imports, stores or page sizes — they give reasoning for the
# `Never name a local variable t` rule already in that entry, and add no new requirement.
#
# Branches and the prediction are fixed in advance in
# logs/PREDICTION-does-inert-prose-break-the-imports-too.txt. Predicted A (imports break
# anyway) at 60%, which is a weak prediction stated weakly.
#
# THE SPEC IS DERIVED, NOT HAND-COPIED, AND VERIFIED BEFORE IT IS USED. A 600-line spec
# copied by hand and edited is a control arm that differs from its baseline in ways nobody
# enumerated. This builds it from `git show 15e25f3^:specs/taskapipro.yaml` plus one
# inert-lines file, then REFUSES unless the diff against pre-edit is exactly twelve added
# lines and zero removed. A control that silently differs somewhere else answers a question
# nobody asked, in the same confident format.
#
# Usage: ./_inert_prose_draw.sh [--check]
set -uo pipefail
cd "$(dirname "$0")"

PRE_REV="15e25f3^:specs/taskapipro.yaml"
INERT_LINES="specs/_inert_twelve_lines.txt"
VARIANT="specs/taskapipro-inert.yaml"
OUT="./generated/taskapipro-inert"
ANCHOR="      POST THREE projects, GET /projects?limit=100, assert EXACTLY 2."

# ---- guards -----------------------------------------------------------------------------
# NEVER OVERWRITE A DRAW. generated/ is gitignored and every landed draw is the evidence
# behind a graded RESULT. A second inert draw is a NEW experiment with its own directory,
# not a re-run that deletes the first one's round-1 log.
if [[ -d "$OUT" ]]; then
  echo "REFUSING: $OUT exists. The control arm has already been drawn once."
  echo "A second inert draw is a new experiment — give it its own OUT, do not overwrite this."
  exit 2
fi
if pgrep -f "\.venv/bin/guildlm-build" > /dev/null; then
  echo "REFUSING: a generation is in flight. Two builds share one GPU exactly once."
  exit 3
fi
# Refuse while a SCHEDULER is up even BETWEEN its jobs — a queue spends real minutes running
# `go test -race` with no guildlm-build process alive while the corpus is still being written.
SCHED=$(pgrep -fl '_sweep_v5.*\.sh|_run_queue.*\.sh|_rebuild_corpus\.sh|_chain_run\.sh|_inert_prose_draw\.sh' \
        | grep -v "^$$ " || true)
if [[ -n "$SCHED" ]]; then
  echo "REFUSING: another scheduler is running — sequence these by hand, do not race them:"
  echo "$SCHED" | sed 's/^/  /'
  exit 3
fi
if ! curl -s -m 5 http://127.0.0.1:8080/v1/models > /dev/null; then
  echo "REFUSING: nothing answering on :8080. Start the MLX server first."
  exit 4
fi
if [[ ! -f "$INERT_LINES" ]]; then
  echo "REFUSING: $INERT_LINES missing — the control content is tracked, not inlined here."
  exit 5
fi

# ---- build the variant spec and PROVE it is the control it claims to be -------------------
PRE=$(mktemp); trap 'rm -f "$PRE"' EXIT
if ! git show "$PRE_REV" > "$PRE" 2>/dev/null; then
  echo "REFUSING: could not read $PRE_REV — the pre-edit baseline is what this is measured against."
  exit 6
fi

N_INERT=$(grep -c '' "$INERT_LINES")
if (( N_INERT != 12 )); then
  echo "REFUSING: $INERT_LINES has $N_INERT lines, need exactly 12."
  echo "The whole control is 'same length, different content'. A different length tests"
  echo "a different thing and would answer branch A ambiguously."
  exit 7
fi

# The anchor must appear EXACTLY ONCE, or the insertion point is not identified.
N_ANCHOR=$(grep -cF "$ANCHOR" "$PRE")
if (( N_ANCHOR != 1 )); then
  echo "REFUSING: the anchor line appears $N_ANCHOR times in the pre-edit spec, need exactly 1."
  echo "  anchor: $ANCHOR"
  exit 8
fi

awk -v anchor="$ANCHOR" -v inert="$INERT_LINES" '
  { print }
  $0 == anchor { while ((getline line < inert) > 0) print line; close(inert) }
' "$PRE" > "$VARIANT"

# THE INTEGRITY CHECK, and it is the reason this script exists rather than a manual edit:
# exactly twelve lines added, zero removed, against the pre-edit baseline.
ADDED=$(diff "$PRE" "$VARIANT" | grep -c '^>' || true)
REMOVED=$(diff "$PRE" "$VARIANT" | grep -c '^<' || true)
if (( ADDED != 12 || REMOVED != 0 )); then
  echo "REFUSING: variant differs from pre-edit by +$ADDED/-$REMOVED, need +12/-0."
  echo "A control that differs somewhere else answers a question nobody asked."
  rm -f "$VARIANT"
  exit 9
fi
# And it must NOT accidentally reproduce the real edit.
if grep -q "THREE PROJECTS, NOT ONE" "$VARIANT"; then
  echo "REFUSING: the variant contains the REAL twelve lines. That is the treatment, not the control."
  rm -f "$VARIANT"
  exit 10
fi
echo "variant spec OK: $VARIANT = pre-edit +12 inert lines, -0, inserted after the anchor"

if [[ "${1:-}" == "--check" ]]; then
  echo "--check: all guards pass, variant built and verified. Not drawing."
  echo "insertion point:"
  grep -n -A 13 -F "$ANCHOR" "$VARIANT" | head -15
  exit 0
fi

# ---- draw, with the flags the four-draw table was built on --------------------------------
# --candidates 2 --shots 2 --max-fix-rounds 5, same model, same server. Changing the spec AND
# the flags in one run is how a control arm becomes unattributable.
LOG="logs/inert-taskapipro-$(date +%m%d%H%M).log"
echo "=== taskapipro INERT CONTROL draw $(date) -> $OUT (log $LOG) ==="
SECONDS=0
.venv/bin/guildlm-build main --spec "$VARIANT" --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
RC=$?
echo "=== guildlm-build exit rc=$RC (${SECONDS}s) ==="
tail -20 "$LOG"

# ---- the outcome variable, read from ROUND 1 of the LOG, never from the tree --------------
# Round 1 describes the AS-DRAWN state. Trees on disk are post-fix, and comparing post-fix
# trees is the population error already made three times on 29 July.
echo
echo "=== OUTCOME VARIABLE: import-path errors in ROUND 1 (as-drawn) ==="
R1=$(awk '/compile\/test FAILED, fix round 1\//{f=1;next} /compile\/test FAILED, fix round 2\//{f=0} f' "$LOG")
if ! grep -q "fix round 1/" "$LOG"; then
  echo "BRANCH C — INCONCLUSIVE: no round-1 marker in the log."
  echo "Either the draw converged with no fix round at all (which is itself informative:"
  echo "0 import errors, same as both pre-edit draws) or it failed before compiling."
  grep -qE "^\[guildlm-build\].*(GREEN|wrote|complete)" "$LOG" && echo "  (log suggests it converged — read it before grading)"
  exit 0
fi
IMP_LINES=$(echo "$R1" | grep -cE "is not in std|could not import" || true)
IMP_UNIQ=$(echo "$R1" | grep -oE "^\[guildlm-build\]     ! [^ ]+: package [^ ]+ is not in std" \
           | sed 's/^\[guildlm-build\]     ! //' | sort -u)
echo "round-1 import-path error LINES: $IMP_LINES"
echo "unique file:line + package:"
echo "${IMP_UNIQ:-  (none)}" | sed 's/^/  /'
echo
if (( IMP_LINES > 0 )); then
  echo "BRANCH A — the imports broke with INERT twelve lines."
  echo "Length/position is SUFFICIENT; the content of the real twelve lines is not the cause."
  echo "N=1. Read the prediction file's limitation section before writing this up as a property."
else
  echo "BRANCH B — the imports are CLEAN with inert twelve lines (pre-edit 0, post-edit 4, this 0)."
  echo "NOT length alone. This does NOT identify what: vocabulary and specific content are"
  echo "still unseparated, and the control is not shape-identical (it cites no measurement)."
fi

echo
echo "=== whole-draw result, for the record ==="
MOD=$(find "$OUT" -name go.mod 2>/dev/null | head -1)
if [[ -z "$MOD" ]]; then echo "RESULT taskapipro-inert: NO go.mod — generation failed early"; exit 0; fi
cd "$(dirname "$MOD")" || exit 0
go build ./... 2>&1 | tail -4; BR=${PIPESTATUS[0]}
go vet ./...   2>&1 | tail -4; VR=${PIPESTATUS[0]}
go test -race ./... 2>&1 | tail -10; TR=${PIPESTATUS[0]}
if [[ $BR -eq 0 && $VR -eq 0 && $TR -eq 0 ]]; then
  echo "RESULT taskapipro-inert: GREEN ✅"
else
  echo "RESULT taskapipro-inert: NOT-GREEN ❌ (build=$BR vet=$VR test=$TR)"
fi
echo "NOTE: GREEN/NOT-GREEN is NOT the outcome variable. The round-1 import count above is."
