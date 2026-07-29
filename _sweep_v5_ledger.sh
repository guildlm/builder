#!/usr/bin/env bash
# Draw ledger as -v5. It was omitted from _sweep_v5.sh's SPECS list.
#
# ledger is 31 rows of the 314-row tracked baseline — the fifth largest artifact — and it is
# the artifact this whole programme is named after (TEETH.md opens on "a ledger that drops
# every credit"; _mutant_check.sh carries that as a canonical mutation). The capstone
# experiment meant to measure whether the corpus improved does not draw it.
#
# Full reasoning: logs/FINDING-the-capstone-omits-the-artifact-the-campaign-is-named-after.txt
#
# This RECOVERS 31 comparable rows instead of documenting their loss, and the comparable
# denominator is the number _sweep_v5.sh's own NEXT block calls the headline.
#
# RUN ORDER: strictly AFTER _sweep_v5_finish.sh prints its completion line. Not after
# guildlm-build disappears — a queue spends real minutes BETWEEN jobs running go test
# -race, and in that window no worker exists while the corpus is very much still being
# written. "No worker is running" and "the scheduler finished" are not the same
# proposition and the gap between them is exactly one job boundary. So this refuses on a
# running scheduler rather than waiting for a quiet worker, and the RESULT count is the
# signal a caller should gate on:
#
#   grep -cE '^RESULT ' logs/sweep-v5-07290011.log   # must be 22 before this runs
set -uo pipefail
cd "$(dirname "$0")"

SWEEP_LOG="logs/sweep-v5-07290011.log"
SPEC=ledger

# NEVER OVERWRITE A LANDED DRAW. _ab_run_v5.sh opens with rm -rf "$OUT".
if [[ -d "./generated/${SPEC}-v5" ]]; then
  echo "REFUSING: generated/${SPEC}-v5 already exists and _ab_run_v5.sh would rm -rf it."
  echo "generated/ is gitignored, so a deleted artifact is gone. Rename it first."
  exit 2
fi

# Match the EXECUTABLE, and exclude THIS process, or the guard matches its own waiters.
SCHEDULERS=$(pgrep -fl '_run_queue.*\.sh|_sweep_v5.*\.sh|_sweep\.sh|_rebuild_corpus\.sh|_chain_run\.sh' | grep -v "^$$ " || true)
if [[ -n "$SCHEDULERS" ]]; then
  echo "REFUSING: another scheduler is running — the finish run must print its completion"
  echo "line first. Do not race them:"
  echo "$SCHEDULERS" | sed 's/^/  /'
  exit 3
fi
if pgrep -f "\.venv/bin/guildlm-build" > /dev/null; then
  echo "REFUSING: a generation is in flight. Two builds share one GPU exactly once."
  exit 3
fi

# The finish run must have LANDED BOTH its specs. This is the real gate: a worker-quiet
# machine proves nothing, 22 RESULT lines prove the sweep drained.
N=$(grep -cE '^RESULT ' "$SWEEP_LOG" 2>/dev/null || echo 0)
if (( N < 22 )); then
  echo "REFUSING: $SWEEP_LOG has $N RESULT lines, need 22 — the finish run has not drained."
  echo "taskapipro and workapi carry the two pending verifications; drawing ledger across"
  echo "them puts a third generation beside a queue that is still working."
  exit 4
fi

if ! curl -s -m 5 http://127.0.0.1:8080/v1/models > /dev/null; then
  echo "REFUSING: nothing answering on :8080."
  exit 5
fi

if [[ "${1:-}" == "--check" ]]; then
  echo "--check: all guards pass. Would draw $SPEC into generated/${SPEC}-v5."
  exit 0
fi

echo "=== ledger v5 draw (recovers 31 comparable rows) starts $(date) ==="
echo "########## SWEEP SPEC: $SPEC (omitted from SPECS, drawn separately) ##########" >> "$SWEEP_LOG"
./_ab_run_v5.sh "$SPEC" >> "$SWEEP_LOG" 2>&1
echo "=== ledger v5 draw complete $(date) ==="
echo "RESULT lines now: $(grep -cE '^RESULT ' "$SWEEP_LOG") (expect 23)"
grep -E "^RESULT ${SPEC}: " "$SWEEP_LOG"
