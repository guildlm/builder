#!/usr/bin/env bash
# Finish the v5 redraw that the 29 July reboot cut in half-flight.
#
# WHAT HAPPENED: _sweep_v5.sh started 00:11 and drew 20 of 22 specs. At 02:08, mid
# taskapipro (spec 21/22), the machine slept/rebooted. The MLX server died, guildlm-build
# died, and generated/taskapipro-v5 was left holding a go.mod and two files of internal/.
# workapi (22/22) never started. Twenty RESULT lines landed; the save point expected 22.
#
# WHY NOT JUST RE-RUN _sweep_v5.sh: it would rm -rf all twenty landed trees and spend
# another six hours redrawing draws that already exist and are already GREEN. Its
# existence-guard is right to refuse — that guard is protecting real evidence.
#
# WHY NOT LEAVE IT AT 20: both of the sweep's own pending verifications are in exactly the
# two specs that did not land. taskapipro carries the projects-paging attached-reason test
# and workapi carries the Delete-404 survives-its-own-redraw test. A 20/22 corpus is not
# 91% of the answer to those two questions, it is 0% of it.
#
# THE PARTIAL TREE IS NOT A LANDED DRAW. generated/taskapipro-v5 has no RESULT line, no
# test files, and 2 of 21 planned files. _ab_run_v5.sh opens with rm -rf "$OUT" and will
# clear it. That is correct here and would NOT be correct for any tree with a RESULT line,
# which is the distinction _sweep_v5.sh's blanket refusal cannot draw and this script can.
#
# ⚠️ THE CAVEAT THAT MUST TRAVEL WITH THESE TWO ROWS: specs 1-20 were drawn against the
# server process that started 00:11 on 29 Jul. These two are drawn against a process
# started ~09:40 after the reboot. _iso_taskapipro.sh exists because this project has
# already been burned by attributing to a spec what belonged to a server restart. The
# confound is weak for the two questions actually being asked — both are binary and
# structural ("does the paging test POST three", "is Delete-404 still asserted"), not
# margin calls on a pass rate — but weak is not zero and the diff must say so. Recorded in
# logs/NOTE-v5-drawn-across-two-server-processes.txt, written by this script.
set -uo pipefail
cd "$(dirname "$0")"

SWEEP_LOG="logs/sweep-v5-07290011.log"
REMAINING=(taskapipro workapi)

if [[ ! -f "$SWEEP_LOG" ]]; then
  echo "REFUSING: $SWEEP_LOG missing — this script appends to the interrupted sweep's log,"
  echo "and writing its rows somewhere else is how a 22-row corpus reads as two 11-row ones."
  exit 2
fi

# Refuse if the interrupted sweep somehow survived, or any other scheduler is up. Match the
# EXECUTABLE path, not a string every waiter's own command line contains (see _sweep_v5.sh).
SCHEDULERS=$(pgrep -fl '_run_queue.*\.sh|_sweep.*\.sh|_rebuild_corpus\.sh|_chain_run\.sh' | grep -v "^$$ " || true)
if [[ -n "$SCHEDULERS" ]]; then
  echo "REFUSING: another scheduler is running — sequence by hand, do not race:"
  echo "$SCHEDULERS" | sed 's/^/  /'
  exit 3
fi
if pgrep -f "\.venv/bin/guildlm-build" > /dev/null; then
  echo "REFUSING: a generation is in flight. Two builds share one GPU exactly once."
  exit 3
fi

# The server must actually be up. The reboot is the whole reason this script exists; running
# it against a dead :8080 would burn both remaining specs into empty trees and the sweep
# would end at 22 RESULT lines that mean nothing.
if ! curl -s -m 5 http://127.0.0.1:8080/v1/models > /dev/null; then
  echo "REFUSING: nothing answering on :8080. Start it first:"
  echo "  ../.mlx-venv/bin/python -m mlx_lm.server --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit --port 8080"
  exit 4
fi

# Guard the DISTINCTION this script is built on: refuse any remaining spec whose tree
# already carries a RESULT line. Only genuinely-unlanded specs may be drawn here.
for s in "${REMAINING[@]}"; do
  if grep -qE "^RESULT ${s}: " "$SWEEP_LOG"; then
    echo "REFUSING: $s ALREADY has a RESULT line in $SWEEP_LOG — that is a landed draw."
    echo "This script only finishes specs that never landed. Nothing was touched."
    exit 5
  fi
done

if [[ "${1:-}" == "--check" ]]; then
  echo "--check: all guards pass. Would draw: ${REMAINING[*]}"
  echo "Would rm -rf: generated/taskapipro-v5 (partial, 2/21 files, no RESULT line)"
  echo "Appending to: $SWEEP_LOG"
  exit 0
fi

cat > logs/NOTE-v5-drawn-across-two-server-processes.txt <<'NOTE'
THE -v5 CORPUS WAS DRAWN ACROSS TWO SERVER PROCESSES — read this beside the redraw diff
=======================================================================================

Specs 1-20 (shortener .. demo-small) were generated 2026-07-29 00:11-02:08 against one
mlx_lm.server process. At 02:08 the machine slept/rebooted mid-taskapipro. Specs 21-22
(taskapipro, workapi) were drawn later the same day against a SECOND server process, same
model and same flags, by _sweep_v5_finish.sh.

WHY THIS IS WRITTEN DOWN RATHER THAN SHRUGGED OFF: _iso_taskapipro.sh exists in this repo
because a red was once attributed to a spec when the honest candidate was drift between two
server processes. The same confound is live here, on the same spec, by coincidence.

HOW MUCH IT ACTUALLY THREATENS: the two questions these draws exist to answer are
structural and binary, not margin calls.
  - taskapipro: does the projects paging test POST THREE and assert 2, or POST one and
    assert 1? A server restart does not change what a test posts.
  - workapi: is the Delete-404 assertion present? Same.
A GREEN/NOT-GREEN verdict, by contrast, IS the kind of margin call that drift can move, so
treat these two specs' green status as weaker evidence than the other twenty's.

WHAT WOULD MAKE IT ZERO: redrawing all 22 against one process, ~6 hours. Not worth it for
this; worth it before any claim that rests on the pass RATE of the v5 corpus as a whole.
NOTE
echo "wrote logs/NOTE-v5-drawn-across-two-server-processes.txt"

echo "=== v5 sweep FINISH (specs 21-22) starts $(date) -> $SWEEP_LOG ==="
for s in "${REMAINING[@]}"; do
  echo "########## SWEEP SPEC: $s (finish run, second server process) ##########" >> "$SWEEP_LOG"
  ./_ab_run_v5.sh "$s" >> "$SWEEP_LOG" 2>&1
done
echo "=== v5 sweep FINISH complete $(date) ==="
echo "RESULT lines now: $(grep -cE '^RESULT ' "$SWEEP_LOG") (expect 22)"
grep -E "^RESULT " "$SWEEP_LOG" | sort
