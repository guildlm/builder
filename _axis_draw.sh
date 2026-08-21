#!/usr/bin/env bash
# Draw the construction-axis arms on ONE eligible process, in the registered order.
#
#     PID=68231 ./_axis_draw.sh                      # the 19 Aug registered eight
#     PID=68231 ONLY=optional ./_axis_draw.sh
#     PID=<p8>  ONLY=transport ./_axis_draw.sh       # 21 Aug: the transport series (see below)
#
# WHY A RUNNER EXISTS AT ALL. Nine arms at ~10 minutes each is 90 minutes of typing the same
# command with one field changed, and 5 August is the precedent this campaign keeps citing: the
# four draws of the first pair were issued by hand, they worked, and the protocol that RAN was
# not the protocol that was COMMITTED. The order below is the order in
# logs/PREREG-is-there-a-construction-axis-or-only-one-inert-family.txt, and it is here so that
# claim can be checked by diffing two files rather than by trusting a memory of what was typed.
#
# ⚠️ THE PID IS RE-CHECKED BEFORE EVERY ARM. "A server restart between arms" is a registered VOID
# condition, and it is invisible in every other check because the port answers either way. The
# probe pins the pid into the ledger per arm and _arm_table.py refuses on a series spanning two
# pids — but that is a check at READ time, after 90 minutes have been spent. This one aborts the
# run at the first arm that would have been drawn against a different process.
#
# ⚠️ ARMS ARE NEVER SKIPPED ON A "BAD" VERDICT. The probe's exit code encodes the VERDICT (1 =
# LONG), not whether the draw went well, and on a treated arm LONG is the effect being tested
# for. A runner that stopped on non-zero would silently drop exactly the arms that flipped.
set -uo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8137}"
PID="${PID:-}"
ONLY="${ONLY:-registered}"
# ⚠️ THE PREFIX IS A PARAMETER BECAUSE A SERIES IS A PROCESS. pid 68231 died mid-series on
# 16 August; its three drawn rows keep the `ax-` prefix and the next process gets its own. A
# prefix reused across two pids is the collision _arm_table.py caught on 11 August.
PREFIX="${PREFIX:-ax-}"

[[ -n "$PID" ]] || { echo "REFUSING: set PID to the eligible process (see the ledger)"; exit 2; }

# suffix:spec — the order registered in AMENDMENT 1 (16 August): the anchor, then the two arms
# that have never been drawn anywhere, then the well-known one. base-close arms bracket each
# block; each must come back ABSENT and byte-identical or the block it closes is void.
REGISTERED=(
  "paraphrase:specs/ledger-sentinelline-placebo.yaml"   # HIGH ANCHOR, replace family, 5 of 5
  "R1:specs/ledger-consaxis-rep1.yaml"                  # NEW, replace  "each one of these"
  "G1:specs/ledger-consaxis-pad1.yaml"                  # NEW, pad      "all of them below"
  "baseclose:specs/ledger-origorder-baseline.yaml"
  "R1-redraw:specs/ledger-consaxis-rep1.yaml"           # registered: BOTH new arms redraw, and
  "G1-redraw:specs/ledger-consaxis-pad1.yaml"           # without them the axis claim cannot be made
  "baseclose2:specs/ledger-origorder-baseline.yaml"
  "F4:specs/ledger-linefloor-4.yaml"                    # LAST (amendment 3): a third reading of an
)                                                       # arm two processes already answered

# explicitly optional in the prereg; their absence is not a gap
OPTIONAL=(
  "L6:specs/ledger-linedose-6.yaml"                     # +14 low anchor, ABSENT 6 of 6
  "F1:specs/ledger-linefloor-1.yaml"                    # +15, the sharpest single arm
  "shipped:specs/ledger-origorder.yaml"                 # +51 positive control
  "baseclose3:specs/ledger-origorder-baseline.yaml"
)

# ⚠️ THE 19 AUGUST LIST ABOVE IS LEFT EXACTLY AS IT RAN. It is the order that produced pid 16225's
# series and the result log points at it; editing it in place would make that claim uncheckable.
# The list below is a SECOND named order, registered on 21 August in
# logs/PREREG-does-the-construction-axis-transport-to-a-second-process.txt, for the process that
# tests whether the axis TRANSPORTS. Two differences from REGISTERED, both registered as
# deliberate before any probe:
#   · shipped +51 moves from the optional tail into the FIFTH treated slot. On pid 16225 it landed
#     ABBREVIATED at draws 13 and 15; "deep in the series" is the one confound a second late draw
#     could not remove, so it is drawn early here. This moves the surprising arm EARLIER, which
#     makes it easier to reproduce and harder to explain away.
#   · shipped is REDRAWN, because it is now an arm the axis story depends on rather than a control
#     nobody expected to move.
# F4 stays optional and last: two processes already answered it and it is not needed to read G1.
TRANSPORT=(
  "paraphrase:specs/ledger-sentinelline-placebo.yaml"   # ANCHOR, replace family, LONG 6 of 6
  "R1:specs/ledger-consaxis-rep1.yaml"                  # PRIMARY, replace  "each one of these"
  "G1:specs/ledger-consaxis-pad1.yaml"                  # PRIMARY, pad      "all of them below"
  "baseclose:specs/ledger-origorder-baseline.yaml"
  "shipped:specs/ledger-origorder.yaml"                 # +51, the control that broke on p7
  "R1-redraw:specs/ledger-consaxis-rep1.yaml"
  "G1-redraw:specs/ledger-consaxis-pad1.yaml"
  "baseclose2:specs/ledger-origorder-baseline.yaml"
  "shipped-redraw:specs/ledger-origorder.yaml"
  "baseclose3:specs/ledger-origorder-baseline.yaml"
)

TRANSPORT_OPTIONAL=(
  "F4:specs/ledger-linefloor-4.yaml"                    # +20 pad anchor, the ladder's 4th process
  "F1:specs/ledger-linefloor-1.yaml"                    # +15, the sharpest single arm
  "L6:specs/ledger-linedose-6.yaml"                     # +14 low anchor, ABSENT 7 of 7
  "baseclose4:specs/ledger-origorder-baseline.yaml"
)

# ⚠️ THE MODAL-VERDICT REDRAW, and it is a RULE, not a reaction to a surprise. The 16 August
# prereg registers it: "Any established arm whose verdict differs from that spec's modal verdict
# across processes is redrawn once BEFORE IT IS WRITTEN DOWN." On pid 83628 both ladder arms came
# back ABBREVIATED where the modal verdict of each is ABSENT (F4: LONG on p4, ABSENT on p5 twice
# and p7; F1: LONG twice on p4, ABSENT twice on p5 and once on p7). They are redrawn here for the
# same reason R1 and G1 were: a verdict that moves the tally is not reported off a single draw.
# ⚠️ IT CANNOT BE A CLEAN POSITION CONTROL AND THIS LIST DOES NOT PRETEND TO BE ONE. These arms
# were drawn 13th and 14th and a redraw is necessarily LATER still; what a redraw tests is
# within-process determinism, not whether depth caused the abbreviation. Only an early draw on
# ANOTHER process can test that, and it is written into the open items instead of faked here.
TRANSPORT_REDRAW=(
  "F4-redraw:specs/ledger-linefloor-4.yaml"
  "F1-redraw:specs/ledger-linefloor-1.yaml"
  "baseclose5:specs/ledger-origorder-baseline.yaml"
)

case "$ONLY" in
  registered)         ARMS=("${REGISTERED[@]}") ;;
  optional)           ARMS=("${OPTIONAL[@]}") ;;
  transport)          ARMS=("${TRANSPORT[@]}") ;;
  transport-optional) ARMS=("${TRANSPORT_OPTIONAL[@]}") ;;
  transport-redraw)   ARMS=("${TRANSPORT_REDRAW[@]}") ;;
  *) echo "REFUSING: ONLY must be registered | optional | transport | transport-optional |"
     echo "          transport-redraw"; exit 2 ;;
esac

echo "=== axis series on pid $PID · ${#ARMS[@]} arms · $ONLY · prefix $PREFIX ==="
for entry in "${ARMS[@]}"; do
  label="${PREFIX}${entry%%:*}"
  spec="${entry#*:}"

  now=$(PORT="$PORT" ./_server_pid.sh) || { echo "ABORT: cannot identify the server"; exit 3; }
  if [[ "$now" != "$PID" ]]; then
    echo "ABORT before $label: the server is now pid $now, not $PID — every arm after a restart"
    echo "       belongs to a different process and the series would be a confound."
    exit 4
  fi

  echo "--- $label ($spec) ---"
  RESTART=0 ROLE=treated SPEC="$spec" PORT="$PORT" ./_probe_process_sentinel.sh "$label" \
    | sed -n 's/^  VERDICT/  VERDICT/p;s/^  REFUSING/  REFUSING/p;s/^  draw stopped/  draw stopped/p'
done
echo "=== done · assemble with: .venv/bin/python ./_arm_table.py --prefix $PREFIX --pid $PID ==="
