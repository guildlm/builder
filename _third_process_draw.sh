#!/usr/bin/env bash
# A THIRD PROCESS, ON THE SAME BOOT: is it the pid, or was it the reboot?
#
# Pre-registered in logs/PREREG-third-process-same-boot.txt at 10:10, before the restart.
#
# Today established: each server process is internally deterministic (measured twice, two
# processes, both zero) and two processes deterministically write DIFFERENT programs from
# identical input (4 CODE files, 3 functions, reproducible across two 2212 draws in different
# states). What separates 4439 from 2212 is still a bundle:
#
#     process identity  ·  a machine REBOOT  ·  a different DAY
#
# Warmth, cache state and uptime were removed from that bundle. These three were not.
#
# This draw holds the boot and the day and changes ONLY the pid: the machine came up 09:20:52
# and has not gone down; 2212 was killed and 42826 started in its place at 10:09:48.
#
#     tree3 == xserver  -> process identity is INERT; the gap tracks the REBOOT, not the pid,
#                          and today's headline narrows from "across a process" to "across a boot"
#     tree3 != xserver  -> process identity IS the variable; reboot and day are unnecessary
#     tree3 == chain6   -> bonus: output comes from a SMALL DISCRETE SET, which is what a variant
#                          chosen once at load time would look like
set -uo pipefail
cd "$(dirname "$0")"

SPEC="specs/taskflow.yaml"              # UNMODIFIED at HEAD, same bytes as all three prior draws
SAMEBOOT="./generated/taskflow-xserver" # 2212, this boot   -> the decisive comparison
OTHERBOOT="./generated/taskflow-chain6" # 4439, previous boot
OUT="./generated/taskflow-proc3"
WANT_PID=42826
WANT_START="Thu Jul 30 10:09:48 2026"
WANT_BOOT="Thu Jul 30 09:20:52 2026"

# ---- the boot must NOT have changed, or this arm is the one it was built to replace ----------
BOOT=$(sysctl -n kern.boottime | sed 's/.*} //')
if [[ "$BOOT" != "$WANT_BOOT" ]]; then
  echo "REFUSING: the machine rebooted since this arm was designed."
  echo "  want boot '$WANT_BOOT'  have '$BOOT'"
  echo "Holding the boot constant IS the manipulation. Without it this is just another restart."
  exit 3
fi

# ---- the server, via the corrected guard ------------------------------------------------------
# NOT `lsof -ti:8080 | head -1`. colima's ssh forward also binds 8080 and that expression returned
# the TUNNEL at 10:10 when asked the same question that returned the model server all morning.
PID=$(./_server_pid.sh) || exit 4
START=$(ps -o lstart= -p "$PID" 2>/dev/null | sed 's/^ *//; s/ *$//')
if [[ "$PID" != "$WANT_PID" || "$START" != "$WANT_START" ]]; then
  echo "REFUSING: :8080 is not the process this draw is pinned to."
  echo "  want pid=$WANT_PID start='$WANT_START'"
  echo "  have pid=$PID start='$START'"
  exit 5
fi
# A fourth process would answer a different question than the one registered.
if [[ "$PID" == "2212" ]]; then echo "REFUSING: that is the OLD process."; exit 5; fi

for t in "$SAMEBOOT" "$OTHERBOOT"; do
  [[ -f "$t/.pre-fix.json" ]] || { echo "REFUSING: $t has no .pre-fix.json."; exit 6; }
done
git diff --quiet HEAD -- "$SPEC" || { echo "REFUSING: $SPEC differs from HEAD."; exit 7; }
pgrep -f "\.venv/bin/guildlm-build" > /dev/null && { echo "REFUSING: a draw is in flight."; exit 8; }
[[ -e "$OUT" ]] && { echo "REFUSING: $OUT exists."; exit 9; }

LOG="logs/taskflow-proc3-$(date +%m%d%H%M).log"
echo "=== taskflow THIRD-PROCESS draw $(date) -> $OUT (log $LOG) ==="
echo "=== pid=$PID start='$START' · boot='$BOOT' UNCHANGED · spec=$SPEC UNMODIFIED ==="
SECONDS=0
.venv/bin/guildlm-build main --spec "$SPEC" --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
echo "=== guildlm-build exit rc=$? (${SECONDS}s) ==="

[[ -f "$OUT/.pre-fix.json" ]] || { echo; echo "VERDICT: UNMEASURED — no snapshot. Redraw."; exit 3; }

echo
echo "########### DECISIVE: same boot, different pid (xserver vs proc3) ###########"
.venv/bin/python _asdrawn_diff.py "$SAMEBOOT" "$OUT"
echo
echo "########### ACROSS BOOTS (chain6 vs proc3) ###########"
.venv/bin/python _asdrawn_diff.py "$OTHERBOOT" "$OUT"
echo
echo "IDENTICAL to xserver -> the pid is inert; the difference tracks the BOOT."
echo "DIFFERS from xserver -> process identity is the variable, and if it also matches chain6"
echo "                        the output comes from a small discrete set rather than being unique."
