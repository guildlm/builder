#!/usr/bin/env bash
# Print the pid of THE MLX SERVER on :8080, or refuse. One copy, because every draw guard needs it.
#
# WHY THIS EXISTS — a near-miss found at 10:10 on 30 July.
# Every draw script pinned the server with:
#
#     PID=$(lsof -ti:8080 2>/dev/null | head -1)
#
# and TWO processes bind port 8080 on this machine:
#
#     ssh    3077   *:8080            colima's forward, appeared 09:34:46
#     Python 42826  127.0.0.1:8080    the actual model server
#
# `lsof -ti:8080` returns BOTH, in unstable order. It returned the MLX pid during every draw this
# morning and returned the SSH TUNNEL at 10:10 when asked the same question the same way. The
# guard was therefore deciding "is this the process my experiment is controlled against?" by
# reading whichever pid lsof happened to list first.
#
# It never produced a wrong draw — the MLX server's own log carries every request, and a draw
# routed to colima's forward would have failed outright rather than quietly. But the guard whose
# entire job is "a restart is invisible in every other check, because the port answers either way"
# was itself answering from the wrong process half the time, which is the same failure one level
# up. The colima listener appeared at 09:34:46, BETWEEN the xserver draw (09:31) and xserver2
# (09:46), so xserver2 was guarded by a coin flip that happened to land right.
#
# THE FIX IS TO ASK A NARROWER QUESTION. Bind address and command are both checked:
#   - 127.0.0.1 specifically, not "port 8080 on any interface" — the model server binds loopback,
#     the tunnel binds *. That alone separates them today.
#   - AND the command must be mlx_lm.server, so a future loopback listener cannot impersonate it.
# Either check alone would pass something the other rejects. Both, or refuse.
set -uo pipefail

CANDIDATES=$(lsof -nP -iTCP@127.0.0.1:8080 -sTCP:LISTEN -t 2>/dev/null || true)
if [[ -z "$CANDIDATES" ]]; then
  echo "REFUSING: nothing is listening on 127.0.0.1:8080." >&2
  exit 4
fi

MATCHES=()
for p in $CANDIDATES; do
  if ps -o command= -p "$p" 2>/dev/null | grep -q "mlx_lm.server"; then
    MATCHES+=("$p")
  fi
done

if [[ ${#MATCHES[@]} -eq 0 ]]; then
  echo "REFUSING: something holds 127.0.0.1:8080 but it is not mlx_lm.server:" >&2
  for p in $CANDIDATES; do ps -o pid,command= -p "$p" 2>/dev/null | tail -1 >&2; done
  exit 5
fi
if [[ ${#MATCHES[@]} -gt 1 ]]; then
  # Two model servers on one port is not a condition any experiment can be controlled against,
  # and picking one would be exactly the arbitrary choice this script exists to remove.
  echo "REFUSING: ${#MATCHES[@]} mlx_lm.server processes hold 127.0.0.1:8080: ${MATCHES[*]}" >&2
  exit 6
fi

echo "${MATCHES[0]}"
