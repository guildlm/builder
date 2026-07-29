#!/usr/bin/env bash
# THE DOSE EXPERIMENT: twelve inert lines into a TASKFLOW entry, same server.
#
# WHAT IS OPEN. On taskapipro, adding twelve lines to a test entry changes generated CODE in
# files that entry never mentions — 4 of 7 untouched files, including a whole getenv helper.
# On taskflow, a ONE-LINE edit (a test rename) was surgical: 11 of 12 untouched files
# identical and the twelfth differing by exactly the renamed function.
#
#   That contrast is across DIFFERENT SPECS. A one-line change to taskapipro has never been
#   drawn, and neither has a twelve-line addition to taskflow. So "one line is surgical,
#   twelve are collateral" is suggestive of a dose relationship and is not a measurement of
#   one. This draw supplies the missing cell.
#
# THE CONTROL IS ALREADY ON DISK. generated/taskflow-chain5 was drawn 15:06 today from the
# current HEAD spec (11520cc, 14:48) on this same server process. Same spec, same flags, same
# server, no added lines. This draw differs from it in exactly one thing.
#
# CHEAP ON PURPOSE: taskflow converges in one fix round, where taskapipro burns seven.
set -uo pipefail
cd "$(dirname "$0")"

SRC="specs/taskflow.yaml"
INERT="specs/_inert_twelve_lines.txt"
VARIANT="specs/taskflow-dose.yaml"
OUT="./generated/taskflow-dose"
ANCHOR='      back ASCENDING by INDEX: got[0].ID == "1", got[1].ID == "2", got[2].ID == "3".'
WANT_PID=4439
WANT_START="Wed Jul 29 09:29:40 2026"

PID=$(lsof -ti:8080 2>/dev/null | head -1)
[[ -z "$PID" ]] && { echo "REFUSING: nothing on :8080."; exit 4; }
START=$(ps -o lstart= -p "$PID" 2>/dev/null | sed 's/^ *//; s/ *$//')
if [[ "$PID" != "$WANT_PID" || "$START" != "$WANT_START" ]]; then
  echo "REFUSING: server is not the process the control (taskflow-chain5) was drawn on."
  echo "  want pid $WANT_PID '$WANT_START'; got pid $PID '$START'"
  echo "A restart makes this a THIRD condition rather than a controlled pair."
  exit 5
fi
[[ -d "$OUT" ]] && { echo "REFUSING: $OUT exists; this draw has been taken."; exit 2; }
pgrep -f "\.venv/bin/guildlm-build" >/dev/null && { echo "REFUSING: a generation is in flight."; exit 3; }
SCHED=$(pgrep -fl '_sweep_v5.*\.sh|_run_queue.*\.sh|_chain_run\.sh|_inert_prose_draw\.sh|_pristine_pre_edit_draw\.sh|_taskflow_dose_draw\.sh' | grep -v "^$$ " || true)
[[ -n "$SCHED" ]] && { echo "REFUSING: another scheduler is running:"; echo "$SCHED" | sed 's/^/  /'; exit 3; }

# ---- derive the variant and PROVE it is +12 and nothing else ------------------------------
# The working tree must match HEAD for this spec, or the control (drawn from HEAD) and the
# treatment differ by more than twelve lines and nobody would see it.
if ! git diff --quiet HEAD -- "$SRC"; then
  echo "REFUSING: $SRC differs from HEAD. taskflow-chain5 was drawn from HEAD, so an"
  echo "uncommitted edit would make this pair differ by more than the twelve lines."
  exit 6
fi
N=$(grep -c '' "$INERT")
(( N == 12 )) || { echo "REFUSING: $INERT has $N lines, need 12."; exit 7; }
(( $(grep -cF "$ANCHOR" "$SRC") == 1 )) || { echo "REFUSING: anchor is not unique."; exit 8; }

awk -v anchor="$ANCHOR" -v inert="$INERT" '
  { print }
  $0 == anchor { while ((getline line < inert) > 0) print line; close(inert) }
' "$SRC" > "$VARIANT"

ADDED=$(diff "$SRC" "$VARIANT" | grep -c '^>' || true)
REMOVED=$(diff "$SRC" "$VARIANT" | grep -c '^<' || true)
if (( ADDED != 12 || REMOVED != 0 )); then
  echo "REFUSING: variant differs by +$ADDED/-$REMOVED, need +12/-0."; rm -f "$VARIANT"; exit 9
fi
# Parse-level check: exactly ONE file entry may differ, the same discipline the taskapipro
# inert arm used. A YAML edit that lands in the wrong entry is invisible in a line diff.
.venv/bin/python - "$SRC" "$VARIANT" <<'PY' || { rm -f "$VARIANT"; exit 10; }
import sys, yaml
a = yaml.safe_load(open(sys.argv[1])); b = yaml.safe_load(open(sys.argv[2]))
assert sorted(a) == sorted(b), "top-level keys changed"
diff = [k for k in a if a[k] != b.get(k)]
assert diff == ["files"], f"keys other than files changed: {diff}"
fa, fb = a["files"], b["files"]
assert len(fa) == len(fb), "file count changed"
d = [fa[i].get("path") for i in range(len(fa)) if fa[i] != fb[i]]
assert d == ["projects_test.go"], f"expected exactly projects_test.go to differ, got {d}"
print(f"  parse check OK: only {d[0]} differs")
PY
echo "spec OK: $VARIANT = HEAD +12 inert lines in projects_test.go, -0"
echo "server OK: pid $PID — the process taskflow-chain5 was drawn on"
[[ "${1:-}" == "--check" ]] && { echo "--check: guards pass. Not drawing."; exit 0; }

LOG="logs/taskflow-dose-$(date +%m%d%H%M).log"
echo "=== taskflow DOSE draw $(date) -> $OUT (log $LOG) ==="
SECONDS=0
.venv/bin/guildlm-build main --spec "$VARIANT" --out "$OUT" \
  --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
  --base-url http://localhost:8080/v1 \
  --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
  --max-fix-rounds 5 > "$LOG" 2>&1
echo "=== guildlm-build exit rc=$? (${SECONDS}s) ==="
echo
echo "=== OUTCOME: untouched-file diff against the control, taskflow-chain5 ==="
echo "Same spec + 12 inert lines vs same spec. Both on 4439. Reference points:"
echo "  taskflow ONE-LINE edit  -> 1 of 12 untouched files differ (the target file only)"
echo "  taskapipro +12 lines    -> 4 of 7 untouched files differ (REAL CODE, none targeted)"
.venv/bin/python _untouched_diff.py generated/taskflow-chain5 "$OUT" \
  logs/taskflow-chain-07291448.log "$LOG"
