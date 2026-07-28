#!/usr/bin/env bash
# ONE queue for today's four closure runs. One process, one list, in order.
#
# Yesterday four independent waiters all parked on `pgrep guildlm-build` and woke inside the
# same 30-second window; only luck kept two generations off one GPU. The rule that came out
# of it: "no worker is running" and "the other scheduler finished" are not the same
# proposition, and the gap between them is exactly one job boundary. So nothing here waits
# on a worker — this script IS the scheduler, and anything that wants to follow it waits on
# THIS pid.
#
# ORDER IS BY INFORMATION PER HOUR, with one exception at the front:
#   1. taskapipro — NOT the cheapest, but the only site in the corpus I left open by my own
#      mistake: I wrote the negative-offset clamp test against /tasks and never mirrored it
#      to /projects, on the same day I recorded the mirror finding. It goes first because a
#      known-open regression outranks a new question.
#   2. usersapi   — 546s last draw, the cheapest run in the corpus. Empty-list closure.
#   3. taskapi    — 1532s. TWO empty-list closures, tasks and projects, because that spec has
#      the same twin-collection shape and this time both get the test up front.
#   4. shortener  — last. Its previous draw died on a PRODUCTION error (an unterminated
#      string literal the fix loop could not repair), so a redraw is partly a coin flip, and
#      it is the spec that historically pays in wall time.
set -uo pipefail
cd "$(dirname "$0")"

echo "=== queue starts $(date) ==="

echo
echo "############ taskapipro: the mirrored projects clamp (draw 3) ############"
./_chain_run.sh taskapipro

echo
echo "############ usersapi: empty list is [] not null ############"
./_chain_run.sh usersapi

echo
echo "############ taskapi: empty list, BOTH collections ############"
./_chain_run.sh taskapi

echo
echo "############ shortener: re-run — Resolve lock closure never got measured ############"
./_shortener_mirrors_run.sh

echo "=== queue complete $(date) ==="
