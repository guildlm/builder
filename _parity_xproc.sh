#!/usr/bin/env bash
# The CORRECTED parity design: one pair per SERVER PROCESS, replicated across processes.
# Pre-registered: logs/PREREG-the-parity-effect-across-processes-not-across-draws.txt
#
#     ./_parity_xproc.sh <pairs>      # default 3
#
# WHY THIS EXISTS. _parity_ab.sh ran 3 pairs in ONE process and all three controls came out
# BYTE-IDENTICAL, as did all three arms — 19 files, 100 minutes apart. The pipeline is a
# deterministic function of (spec, flags, server process), so "3 pairs" was three copies of one
# observation: effective n = 1 per condition. Meanwhile the campaign has measured that a DIFFERENT
# process rewrites 3 to 6 code files from identical input, and that process identity — not the
# boot, not the day — is the variable. So the PAIR stays inside a process (that is what makes it a
# controlled comparison) and the REPLICATION crosses processes (that is what makes three of them
# worth more than one).
#
# ⚠️ THE PAIR MUST NOT STRADDLE A RESTART. That is the one thing this design can get wrong, and it
# is checked explicitly before each draw rather than assumed from the ordering of the calls.
#
# ⚠️ PREDICTION IS 35%, NOT 50% — revised down before any run, on prior evidence: the effect is one
# sentence changing one file, and a process change independently rewrites 3-6. If store.go is in
# the volatile set for some process, the CONTROL can consolidate there, which is the reject
# condition. Read the pre-registration before reading any table this prints.
set -uo pipefail
cd "$(dirname "$0")"

PAIRS="${1:-3}"
SPEC="specs/ledger-origorder.yaml"
MODEL="mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
EXAMPLES="examples/verified_contracts.jsonl"

source ./_harness_lock.sh

echo "=== parity ACROSS PROCESSES · $PAIRS pairs · spec=$SPEC · $(date) ==="
harness_lock_init "$0" "$SPEC" "$EXAMPLES"

PAIR_PID=""

draw () {   # draw <out> <log> <enable_rules>
  local out="$1" log="$2" rules="$3"
  local pid; pid=$(./_server_pid.sh) || return 4
  # the pair's process is pinned when the pair starts, NOT globally: crossing processes is the
  # point of this runner, so the check is "same process as my partner draw", not "same as launch".
  [[ "$pid" == "$PAIR_PID" ]] || { echo "REFUSING: pair straddles a restart ($PAIR_PID -> $pid)"; return 5; }
  harness_check || return $?
  pgrep -f "\.venv/bin/guildlm-build" >/dev/null && { echo "REFUSING: a draw is in flight."; return 8; }
  [[ -e "$out" ]] && { echo "REFUSING: $out exists."; return 9; }
  echo "--- draw $out (rules='$rules') pid=$pid $(date +%H:%M:%S)"
  GUILDLM_ENABLE_RULES="$rules" .venv/bin/guildlm-build main --spec "$SPEC" --out "$out" \
    --model "$MODEL" --base-url http://localhost:8080/v1 \
    --candidates 2 --examples "$EXAMPLES" --shots 2 \
    --max-fix-rounds 5 > "$log" 2>&1
  echo "--- rc=$? $(date +%H:%M:%S)"
  echo "$pid" > "$out/.server_pid"    # the pid travels WITH the tree, so a later join cannot guess
}

for i in $(seq 1 "$PAIRS"); do
  echo
  echo "===== pair $i: fresh server process ====="
  ./_server_restart.sh || { echo "ABORT: restart failed for pair $i"; exit $?; }
  PAIR_PID=$(./_server_pid.sh) || exit 4
  echo "  pair $i pinned to pid $PAIR_PID"
  draw "./generated/ledger-xproc-ctl-$i" "logs/ledger-xproc-ctl-$i.log" ""                     || exit $?
  draw "./generated/ledger-xproc-arm-$i" "logs/ledger-xproc-arm-$i.log" "interface_only_scope" || exit $?
done

echo
echo "=== VERDICT — the pre-registered endpoint, same grader as _parity_ab.sh ==="
.venv/bin/python _parity_grade.py $(for i in $(seq 1 "$PAIRS"); do echo "./generated/ledger-xproc-ctl-$i" "./generated/ledger-xproc-arm-$i"; done)
echo
echo "=== and the AS-DRAWN comparison — never the repaired trees on disk ==="
echo "    Use _asdrawn_diff.py: on 31 July I spent two hours comparing a finished tree against a"
echo "    mid-generation one and built eight findings on a drift that did not exist."
for i in $(seq 1 "$PAIRS"); do
  c="./generated/ledger-xproc-ctl-$i" a="./generated/ledger-xproc-arm-$i"
  printf '  pair %d  ctl pid %s   arm pid %s\n' "$i" "$(cat "$c/.server_pid" 2>/dev/null || echo '?')" "$(cat "$a/.server_pid" 2>/dev/null || echo '?')"
  .venv/bin/python _asdrawn_diff.py "$c" "$a" 2>&1 | sed 's/^/      /' | head -6
done
