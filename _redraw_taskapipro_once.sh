#!/usr/bin/env bash
# The ONE additional taskapipro draw permitted by
# logs/NOTE-the-rule-for-redrawing-taskapipro-decided-in-advance.txt.
#
# Read that note before running this. The rule was fixed BEFORE any second draw existed,
# precisely so this script cannot become "draw until something compiles":
#
#   * one more draw, after ledger, and NOT AGAIN
#   * both draws reported, with the denominator — "two draws, N compiled"
#   * the first tree is PRESERVED, not replaced
#   * if the second is also red, taskapipro is uncomparable and there is no third draw
#
# This script enforces the parts a script can enforce. The reporting rule is the caller's,
# and the note is the evidence against reporting it any other way.
set -uo pipefail
cd "$(dirname "$0")"

SWEEP_LOG="logs/sweep-v5-07290011.log"
EVIDENCE="./generated/taskapipro-v5-red-evidence"
TREE="./generated/taskapipro-v5"

# ONE DRAW, ENFORCED BY THE FILESYSTEM. If the evidence directory already exists, a second
# draw has already happened and this is the third. Refuse. This is the only guard that
# actually stops the failure mode the note is about, because every other check would pass
# on attempt three exactly as it passed on attempt two.
if [[ -d "$EVIDENCE" ]]; then
  echo "REFUSING: $EVIDENCE exists, so the one permitted redraw has already been taken."
  echo "The rule allows two draws total and no third — see"
  echo "  logs/NOTE-the-rule-for-redrawing-taskapipro-decided-in-advance.txt"
  echo "A third draw would start estimating a rate, and a rate estimated by drawing until"
  echo "something compiles is not a rate. If a third is genuinely wanted it is a NEW"
  echo "experiment with its own declared rule, not a re-run of this script."
  exit 2
fi

if pgrep -f "\.venv/bin/guildlm-build" > /dev/null; then
  echo "REFUSING: a generation is in flight."; exit 3
fi
SCHED=$(pgrep -fl '_sweep_v5.*\.sh|_run_queue.*\.sh|_chain_run\.sh' | grep -v "^$$ " || true)
if [[ -n "$SCHED" ]]; then
  echo "REFUSING: another scheduler is running:"; echo "$SCHED" | sed 's/^/  /'; exit 3
fi

# AFTER LEDGER. The note sequences this behind the ledger draw, whose 31 missing rows have
# no ambiguity about why they are missing — a stronger claim on the GPU than a second
# attempt at an artifact that already has a recorded outcome.
N=$(grep -cE '^RESULT ' "$SWEEP_LOG" 2>/dev/null || echo 0)
if (( N < 23 )); then
  echo "REFUSING: $SWEEP_LOG has $N RESULT lines, need 23 (22 specs + ledger)."
  echo "ledger comes first: ./_sweep_v5_ledger.sh"
  exit 4
fi

if [[ ! -d "$TREE" ]]; then echo "REFUSING: $TREE missing — nothing to preserve"; exit 5; fi
if ! curl -s -m 5 http://127.0.0.1:8080/v1/models > /dev/null; then
  echo "REFUSING: nothing answering on :8080."; exit 6
fi

FIRST=$(grep -E "^RESULT taskapipro: " "$SWEEP_LOG" | head -1)

if [[ "${1:-}" == "--check" ]]; then
  echo "--check: guards pass. Would preserve $TREE as $EVIDENCE and draw taskapipro once."
  echo "first draw was: $FIRST"
  exit 0
fi

# PRESERVE, DO NOT DELETE. -red-evidence deliberately does NOT end in -v5, so _hole_hunt's
# `*-v5` glob still matches exactly one taskapipro tree whichever way the redraw goes.
mv "$TREE" "$EVIDENCE"
echo "preserved first draw -> $EVIDENCE (does not match *-v5, so the sweep still sees one)"

# Its own log. The sweep log keeps one RESULT line per spec; a second line for taskapipro
# would make `grep -c RESULT` report 24 for 23 specs and quietly break every gate that
# counts it, including two in this repo.
LOG2="logs/redraw-taskapipro-2nd-$(date +%m%d%H%M).log"
echo "=== taskapipro SECOND draw (the one permitted redraw) $(date) -> $LOG2 ==="
./_ab_run_v5.sh taskapipro > "$LOG2" 2>&1
SECOND=$(grep -E "^RESULT taskapipro: " "$LOG2" | tail -1)

echo
echo "BOTH DRAWS — report them together, this is the rule:"
echo "  draw 1  ${FIRST:-<none>}"
echo "  draw 2  ${SECOND:-<none>}"
echo
echo "If draw 2 is GREEN its rows may enter the capstone diff, CITING the advance-decision"
echo "note beside them, because one-of-two is a different fact from one-of-one."
echo "If draw 2 is also NOT-GREEN, taskapipro is uncomparable: 110 of 314 baseline rows dead."
