#!/usr/bin/env bash
# Find an eligible process for the axis series and hand it STRAIGHT to the draw.
#
#     PREFIX=ax2- ./_axis_hunt.sh                      # up to 10 baseline probes, screen, then draw
#     PREFIX=ax2- MAX=10 DRAW=0 ./_axis_hunt.sh         # find one and stop
#     PREFIX=ax4- ORDER=transport ./_axis_hunt.sh       # 21 Aug: the transport series
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
MAX="${MAX:-10}"          # CLASSIFYING baseline probes — see AMENDMENT 2 in the prereg
ATTEMPTS="${ATTEMPTS:-30}"  # hard stop, so a GPU that kills everything cannot loop forever
START="${START:-1}"       # label numbering continues across relaunches; a reused label is fatal
DRAW="${DRAW:-1}"
ORDER="${ORDER:-registered}"  # which arm list _axis_draw.sh runs; 21 Aug's transport series is `transport`
BASE_SPEC="specs/ledger-origorder-baseline.yaml"
SCREEN_SPEC="specs/ledger-ownplacebo.yaml"

verdict_of () {  # verdict_of <probe stdout>  -> the VERDICT field, or the empty string
  sed -n 's/.*VERDICT: \([A-Z-]*\).*/\1/p' <<<"$1" | tail -1
}

spent=0
for ((i = START; i < START + ATTEMPTS; i++)); do
  (( spent < MAX )) || break
  echo "=== baseline probe attempt $i · classifying probes spent $spent of $MAX ==="
  out=$(SPEC="$BASE_SPEC" PORT="$PORT" ./_probe_process_sentinel.sh "${PREFIX}b${i}" 2>&1)
  # ⚠️ A REFUSAL IS NOT A VOID DRAW. On 17 August a killed launch left one guildlm-build orphan
  # in flight; every subsequent probe exited 8 ("a draw is in flight") in under a second, this
  # loop read the empty verdict as "void, classifies nothing" and spent all 30 ATTEMPTS in ~20s
  # without a single draw. A probe that refuses never started; retrying it changes nothing.
  if grep -q "REFUSING" <<<"$out"; then
    echo "  ABORT: the probe refused — fix the cause, then relaunch with START=$((i + 1))"
    grep "REFUSING" <<<"$out"
    exit 6
  fi
  v=$(verdict_of "$out")
  pid=$(PORT="$PORT" ./_server_pid.sh 2>/dev/null || echo "")
  echo "  baseline verdict: ${v:-<none>}  (pid ${pid:-<gone>})"

  # ⚠️ A PROBE THE GPU KILLED CLASSIFIES NOTHING AND DOES NOT SPEND THE BUDGET — prereg
  # AMENDMENT 2, written before the budget bound. It never reached a declarer, so it carries none
  # of the information that makes this campaign's central claim conditional. ATTEMPTS is the
  # separate, cruder guard that keeps a dying machine from looping forever.
  case "$v" in
    VOID-*|NO-FILE|"") echo "  -> void, classifies nothing; re-probing WITHOUT spending budget"
                       continue ;;
  esac
  spent=$((spent + 1))

  case "$v" in
    ABSENT) ;;
    *) echo "  -> discarded, re-probing"; continue ;;
  esac
  [[ -n "$pid" ]] || { echo "  -> the server is gone; re-probing"; continue; }

  echo "=== screen on pid $pid ==="
  out=$(RESTART=0 ROLE=screen SPEC="$SCREEN_SPEC" PORT="$PORT" \
        ./_probe_process_sentinel.sh "${PREFIX}screen${i}" 2>&1)
  if grep -q "REFUSING" <<<"$out"; then
    echo "  ABORT: the screen probe refused — fix the cause, then relaunch with START=$((i + 1))"
    grep "REFUSING" <<<"$out"
    exit 6
  fi
  s=$(verdict_of "$out")
  echo "  screen verdict: ${s:-<none>}"
  # ⚠️ NULL MEANS ABSENT, AND THIS LINE HAD IT WRONG UNTIL 17 AUGUST 00:4x. It read
  #     if [[ "$s" != "ABSENT" && "$s" != ABBREVIATED* ]]
  # i.e. it would have accepted a process whose CONTENT-FREE edit moved the declarer to
  # ABBREVIATED. That is not a null — 11 August's whole correction was that ABBREVIATED is ABOVE
  # ABSENT and that off-line edits which look inert in a binary reading are not inert at
  # three-valued resolution. A process the placebo moves has already told you it moves for
  # nothing, which is exactly what the screen exists to detect. No screen returned ABBREVIATED
  # tonight, so nothing was admitted under the loose test; it is fixed before the next relaunch
  # rather than after it mattered.
  if [[ "$s" != "ABSENT" ]]; then
    echo "  -> NOT eligible (the content-free edit moved it, or the draw voided); re-probing"
    continue
  fi

  # ⚠️ $i is the LABEL index, which continues across relaunches; $spent is the count that the
  # budget is about. On 19 August this line said "after 25 baseline probes" for a process found
  # on the FIRST classifying probe of its launch (label b25) — a hand-readable number that was
  # wrong by 24. Both are printed now, and named.
  echo "=== ELIGIBLE: pid $pid (baseline ABSENT, screen $s) — label ${PREFIX}b${i}, $spent classifying probe(s) spent under this launch ==="
  if [[ "$DRAW" == "1" ]]; then
    # ⚠️ THE ARM LIST IS PASSED EXPLICITLY, NOT INHERITED. _axis_draw.sh defaults to ONLY=registered
    # (the 19 August order) and would have picked up an exported ONLY from this shell silently —
    # i.e. which protocol ran would have depended on how the hunt was invoked, which is the exact
    # class of mistake the runner exists to prevent. ORDER names the registered list for the night.
    PID="$pid" PREFIX="$PREFIX" PORT="$PORT" ONLY="$ORDER" ./_axis_draw.sh
  fi
  exit 0
done

# ⚠️ THIS IS A RESULT, NOT A FAILURE, and the prereg says so: no eligible process within the
# probe budget is recorded and no arm is run.
echo "=== NO ELIGIBLE PROCESS in $MAX CLASSIFYING baseline probes — that is the registered outcome ==="
exit 1
