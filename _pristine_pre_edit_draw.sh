#!/usr/bin/env bash
# THE DECIDING DRAW: the UNMODIFIED pre-edit spec, on the SAME server process, verified.
#
# WHAT IS OPEN. Twelve lines added to taskapipro's projects entry coincided with three
# implementation files losing their module prefix. The inert control (17:36) killed the
# CONTENT hypothesis — twelve lines of prose about variable naming produce the identical
# defect, byte for byte. What it could not kill is the SERVER:
#
#     draw     projects entry           server        round-1 verdict
#     chain4   PRE-edit                 28 Jul        FINE, measured
#     chain5   PRE-edit                 29 Jul/4439   UNMEASURED (internal/api never reached)
#     v5 x2    POST-edit (+12 real)     29 Jul/4439   DEFECT
#     inert    PRE-edit  (+12 inert)    29 Jul/4439   DEFECT
#
#   Every DEFECT is on 4439. The only measured FINE is on another server on another day.
#   "Twelve more lines in that entry" and "this server process" fit all five rows equally.
#
# THIS DRAW SEPARATES THEM, and it is one draw:
#     FINE, measured  -> the added LINES cause it. The spec attribution recovers.
#     DEFECT          -> the SERVER causes it. The twelve-line edit is exonerated of the
#                        import defect entirely and today's largest finding loses its
#                        remaining half.
#     UNMEASURED      -> a different package failed first. Says nothing. Redraw.
#
# It is the draw chain5 was supposed to be. chain5 came back masked, which is the only reason
# this is still open, so this script REFUSES to report a count and defers to the grader that
# knows the difference.
#
# ⚠️ ITS EXPECTED VALUE CHANGED AT 18:17, WHICH IS WHY IT IS BEING RUN AFTER ALL. At 18:10 this
# draw was shelved: its condition is chain5's condition, generation in a fixed condition is
# byte-identical here, so it was expected to reproduce chain5 — including chain5's round 1
# dying in internal/store before internal/api was ever built. That is the UNMEASURED verdict
# again, and an hour of GPU for a 1-in-4 shot was a bad trade.
#
# `<out>/.pre-fix.json` removes the blocker entirely. The question is "did the MODEL write the
# unprefixed path", which is a property of the source, not of whether a compiler reached it.
# The snapshot is read directly by _grade_asdrawn_imports.py and cannot be masked. So the
# draw reproducing chain5 is now the GOOD case rather than the wasted one: it tells us what
# chain5 would have shown.
set -uo pipefail
cd "$(dirname "$0")"

PRE_REV="15e25f3^:specs/taskapipro.yaml"
VARIANT="specs/taskapipro-preedit.yaml"
OUT="./generated/taskapipro-preedit"
# The server this experiment is controlled against. Captured 17:37 on 29 July.
WANT_PID=4439
WANT_START="Wed Jul 29 09:29:40 2026"

# ---- the premise, VERIFIED rather than assumed -------------------------------------------
# THE ENTIRE VALUE OF THIS DRAW IS "SAME SERVER PROCESS". If mlx_lm.server has restarted, this
# becomes a THIRD condition rather than a control, and it would look exactly like a result.
# A restart is invisible in every other check — the port answers either way — so the identity
# is pinned to pid AND start time. pid alone is reusable after a reboot; start time alone
# could match a coincidence. Together they name one process.
PID=$(lsof -ti:8080 2>/dev/null | head -1)
if [[ -z "$PID" ]]; then
  echo "REFUSING: nothing is listening on :8080."
  exit 4
fi
START=$(ps -o lstart= -p "$PID" 2>/dev/null | sed 's/^ *//; s/ *$//')
if [[ "$PID" != "$WANT_PID" || "$START" != "$WANT_START" ]]; then
  echo "REFUSING: the server is not the process this experiment is controlled against."
  echo "  want: pid $WANT_PID started '$WANT_START'"
  echo "  got:  pid $PID started '$START'"
  echo
  echo "A restarted server makes this a THIRD condition, not a control — and it would read as"
  echo "a result. Either restore the comparison by re-deriving it against the new process"
  echo "(which means redrawing the POST-edit arm too), or update WANT_PID/WANT_START and say"
  echo "in the commit that the control was rebased."
  exit 5
fi

if [[ -d "$OUT" ]]; then
  echo "REFUSING: $OUT exists. This draw has been taken."
  echo "A second one is a new experiment with its own directory and its own declared rule —"
  echo "drawing until something compiles is not a measurement."
  exit 2
fi
if pgrep -f "\.venv/bin/guildlm-build" > /dev/null; then
  echo "REFUSING: a generation is in flight. Two builds share one GPU exactly once."
  exit 3
fi
SCHED=$(pgrep -fl '_sweep_v5.*\.sh|_run_queue.*\.sh|_rebuild_corpus\.sh|_chain_run\.sh|_inert_prose_draw\.sh|_pristine_pre_edit_draw\.sh' \
        | grep -v "^$$ " || true)
if [[ -n "$SCHED" ]]; then
  echo "REFUSING: another scheduler is running — sequence these, do not race them:"
  echo "$SCHED" | sed 's/^/  /'
  exit 3
fi

# ---- the spec: derived from git and proved IDENTICAL to pre-edit ---------------------------
# The inert arm had to prove "+12 lines and nothing else". This arm has the stricter job of
# proving NOTHING CHANGED — it is the pre-edit spec exactly. specs/taskapipro.yaml on disk is
# the POST-edit state, so hand-copying is how the wrong arm gets drawn and nobody notices.
PRE=$(mktemp); trap 'rm -f "$PRE"' EXIT
if ! git show "$PRE_REV" > "$PRE" 2>/dev/null; then
  echo "REFUSING: could not read $PRE_REV — that revision IS the arm."
  exit 6
fi
cp "$PRE" "$VARIANT"
ADDED=$(diff "$PRE" "$VARIANT" | grep -c '^>' || true)
REMOVED=$(diff "$PRE" "$VARIANT" | grep -c '^<' || true)
if (( ADDED != 0 || REMOVED != 0 )); then
  echo "REFUSING: the variant differs from pre-edit by +$ADDED/-$REMOVED; it must be identical."
  rm -f "$VARIANT"; exit 7
fi
if grep -q "THREE PROJECTS, NOT ONE" "$VARIANT"; then
  echo "REFUSING: the variant contains the twelve-line edit. That is the treatment arm."
  rm -f "$VARIANT"; exit 8
fi
if grep -q "NEVER NAME A LOCAL VARIABLE t" "$VARIANT"; then
  echo "REFUSING: the variant contains the INERT twelve lines. That arm is already drawn."
  rm -f "$VARIANT"; exit 9
fi
echo "spec OK: $VARIANT is byte-identical to $PRE_REV, and carries neither twelve-line block"
echo "server OK: pid $PID, started $START — the process both v5 draws and the inert arm used"

if [[ "${1:-}" == "--check" ]]; then
  echo "--check: guards pass. Not drawing."
  exit 0
fi

# ---- draw, with the flags every other arm used --------------------------------------------
LOG="logs/preedit-taskapipro-$(date +%m%d%H%M).log"
echo "=== taskapipro PRISTINE PRE-EDIT draw $(date) -> $OUT (log $LOG) ==="
SECONDS=0
.venv/bin/guildlm-build main --spec "$VARIANT" --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
echo "=== guildlm-build exit rc=$? (${SECONDS}s) ==="

# ---- grade with the instrument that knows a masked zero from a measured one ----------------
# NOT a count. chain5 read 0 and meant nothing, and every table that treated it as a 0 was
# wrong for six hours. This script deliberately does NOT print a branch of its own — the
# previous runner did, was written before the masking problem was known, and its verdict had
# to be publicly superseded.
echo
echo "=== PRIMARY VERDICT: what the MODEL WROTE, from the pre-repair snapshot ==="
echo "This is the one that cannot be masked. A compiler that never reached internal/api says"
echo "nothing about its imports; the source says what it says."
.venv/bin/python _grade_asdrawn_imports.py "$OUT"
SNAP=$?
echo
echo "=== SECONDARY: round-1 compiler output (may be UNMEASURED — that is chain5's outcome) ==="
.venv/bin/python _grade_import_defect.py "$LOG"
RC=$?
echo
echo "READ THE SNAPSHOT VERDICT, NOT THE LOG ONE, WHEN THEY DISAGREE:"
echo "  CORRECT    -> the pre-edit spec writes prefixed imports on THIS server. The twelve"
echo "                added lines cause the defect; the spec attribution recovers."
echo "  UNPREFIXED -> the pre-edit spec writes them too. The SERVER causes it and the"
echo "                twelve-line edit is exonerated of the import defect entirely."
echo "  (snapshot rc=$SNAP · log-grader rc=$RC — a log UNMEASURED alongside a snapshot verdict"
echo "   is the expected shape, not a conflict: it means the compiler never looked.)"
