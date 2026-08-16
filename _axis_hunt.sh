#!/usr/bin/env bash
# Find an eligible process for the axis series and hand it STRAIGHT to the draw.
#
#     PREFIX=ax2- ./_axis_hunt.sh            # up to 10 baseline probes, then screen, then draw
#     PREFIX=ax2- MAX=10 DRAW=0 ./_axis_hunt.sh   # find one and stop
#
# WHY THE HUNT AND THE DRAW ARE ONE JOB. Every minute an eligible process sits idle is a minute
# it can die in, and on 16 August one did — the Metal driver killed pid 68231 between the anchor
# and the first new arm, after it had been found on the FIRST probe. Eligible processes are the
# scarce resource in this campaign (1 to 12 probes to find one, ~8-11 minutes each); the arms are
# what they are for. So the moment a process passes both gates, the arms start.
#
# THE TWO GATES, unchanged and in this order — see the prereg:
#   1. BASELINE must be ABSENT. LONG is uninformative and discarded. ⚠️ ABBREVIATED is
#      "informative" under the standing definition and is DISCARDED HERE ANYWAY, because every
#      arm in this series is a movement FROM ABSENT and cannot be read from halfway up. That is
#      why this script reads the VERDICT and does not branch on the probe's exit code: the exit
#      code says LONG-or-not, which is a different question.
#   2. SCREEN (+54, content-free, same purpose) must be null. A process that flips on it has zero
#      discriminating power and every arm on it would be a positive arm.
# Every probe, kept AND discarded, is in logs/PROBE-LEDGER.txt — the probe writes it, not this.
set -uo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8137}"
PREFIX="${PREFIX:-ax2-}"
MAX="${MAX:-10}"
DRAW="${DRAW:-1}"
BASE_SPEC="specs/ledger-origorder-baseline.yaml"
SCREEN_SPEC="specs/ledger-ownplacebo.yaml"

verdict_of () {  # verdict_of <probe stdout>  -> the VERDICT field, or the empty string
  sed -n 's/.*VERDICT: \([A-Z-]*\).*/\1/p' <<<"$1" | tail -1
}

for ((i = 1; i <= MAX; i++)); do
  echo "=== baseline probe $i of $MAX ==="
  out=$(SPEC="$BASE_SPEC" PORT="$PORT" ./_probe_process_sentinel.sh "${PREFIX}b${i}" 2>&1)
  v=$(verdict_of "$out")
  pid=$(PORT="$PORT" ./_server_pid.sh 2>/dev/null || echo "")
  echo "  baseline verdict: ${v:-<none>}  (pid ${pid:-<gone>})"

  case "$v" in
    ABSENT) ;;
    *) echo "  -> discarded, re-probing"; continue ;;
  esac
  [[ -n "$pid" ]] || { echo "  -> the server is gone; re-probing"; continue; }

  echo "=== screen on pid $pid ==="
  out=$(RESTART=0 ROLE=screen SPEC="$SCREEN_SPEC" PORT="$PORT" \
        ./_probe_process_sentinel.sh "${PREFIX}screen${i}" 2>&1)
  s=$(verdict_of "$out")
  echo "  screen verdict: ${s:-<none>}"
  if [[ "$s" != "ABSENT" && "$s" != ABBREVIATED* ]]; then
    echo "  -> NOT eligible (the content-free edit moved it, or the draw voided); re-probing"
    continue
  fi

  echo "=== ELIGIBLE: pid $pid (baseline ABSENT, screen $s) after $i baseline probes ==="
  if [[ "$DRAW" == "1" ]]; then
    PID="$pid" PREFIX="$PREFIX" PORT="$PORT" ./_axis_draw.sh
  fi
  exit 0
done

# ⚠️ THIS IS A RESULT, NOT A FAILURE, and the prereg says so: no eligible process within the
# probe budget is recorded and no arm is run.
echo "=== NO ELIGIBLE PROCESS in $MAX baseline probes — that is the registered outcome ==="
exit 1
