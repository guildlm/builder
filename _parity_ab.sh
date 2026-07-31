#!/usr/bin/env bash
# Does withholding the INTERFACE/IMPL PARITY clause stop the interface file absorbing the
# implementation? Pre-registered: logs/PREREG-withhold-the-parity-clause-from-an-interface-only-file.txt
#
#     ./_parity_ab.sh <pairs>       # default 3
#
# CONTROL and ARM differ by ONE environment variable and share a commit AND a server process. The
# control is drawn fresh rather than reused from yesterday's pairA-p6/p7/p8, because those came from
# a different process and a different builder.py — five harness edits landed today.
#
# SPEC IS ledger-origorder.yaml, store.go FIRST. That is the order that consolidates (3/3 on the
# paired arms). specs/ledger.yaml, the current reordered spec, already splits correctly four draws
# for four and would show nothing.
#
# ⚠️ NOT `lsof -ti:8080 | head -1` — colima's ssh forward also binds 8080. See _server_pid.sh.
set -uo pipefail
cd "$(dirname "$0")"

PAIRS="${1:-3}"
SPEC="specs/ledger-origorder.yaml"
MODEL="mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
EXAMPLES="examples/verified_contracts.jsonl"

WANT_PID=$(./_server_pid.sh) || exit 4

# The freeze guard lives in _harness_lock.sh so this runner and _parity_xproc.sh cannot drift
# apart; _selftest_freeze_guard.sh extracts its lines from there.
source ./_harness_lock.sh

echo "=== parity A/B · $PAIRS pairs · spec=$SPEC · server pid=$WANT_PID · $(date) ==="
harness_lock_init "$0" "$SPEC" "$EXAMPLES"

draw () {   # draw <out> <log> <enable_rules>
  local out="$1" log="$2" rules="$3"
  local pid; pid=$(./_server_pid.sh) || return 4
  [[ "$pid" == "$WANT_PID" ]] || { echo "REFUSING: server pid changed $WANT_PID -> $pid"; return 5; }
  harness_check || return $?
  pgrep -f "\.venv/bin/guildlm-build" >/dev/null && { echo "REFUSING: a draw is in flight."; return 8; }
  [[ -e "$out" ]] && { echo "REFUSING: $out exists."; return 9; }
  echo "--- draw $out (GUILDLM_ENABLE_RULES='$rules') $(date +%H:%M:%S)"
  GUILDLM_ENABLE_RULES="$rules" .venv/bin/guildlm-build main --spec "$SPEC" --out "$out" \
    --model "$MODEL" --base-url http://localhost:8080/v1 \
    --candidates 2 --examples "$EXAMPLES" --shots 2 \
    --max-fix-rounds 5 > "$log" 2>&1
  echo "--- rc=$? $(date +%H:%M:%S)"
}

for i in $(seq 1 "$PAIRS"); do
  draw "./generated/ledger-parity-ctl-$i" "logs/ledger-parity-ctl-$i.log" ""                     || exit $?
  draw "./generated/ledger-parity-arm-$i" "logs/ledger-parity-arm-$i.log" "interface_only_scope" || exit $?
done

echo
echo "=== VERDICT — the pre-registered endpoint is per draw and binary ==="
.venv/bin/python _parity_grade.py $(for i in $(seq 1 "$PAIRS"); do echo "./generated/ledger-parity-ctl-$i" "./generated/ledger-parity-arm-$i"; done)
echo
echo "  Read the pre-registration before reading that table: the arm was predicted to SPLIT on at"
echo "  least 2 of 3, at only 45%, because the implementer file gets the same clause and already"
echo "  resists it. A null does NOT revive 'the model cannot split a package'."
