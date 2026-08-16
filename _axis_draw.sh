#!/usr/bin/env bash
# Draw the construction-axis arms on ONE eligible process, in the registered order.
#
#     PID=68231 ./_axis_draw.sh            # the registered nine
#     PID=68231 ONLY=optional ./_axis_draw.sh
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

case "$ONLY" in
  registered) ARMS=("${REGISTERED[@]}") ;;
  optional)   ARMS=("${OPTIONAL[@]}") ;;
  *) echo "REFUSING: ONLY must be 'registered' or 'optional'"; exit 2 ;;
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
