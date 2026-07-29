#!/usr/bin/env bash
# TWO DRAWS, one server: does twelve lines of inert prose perturb a spec nobody ever edited?
#
# Design and branches: logs/PREDICTION-does-spec-growth-perturb-an-untouched-spec.txt
# Motivation:          logs/RESULT-the-capstone-drift-may-be-spec-growth-not-redraw.txt
#
# WHY BOTH ARMS ARE DRAWN NOW. jsoncodec-v5 exists, but it was drawn 01:55 — before server
# 4439 started at 09:29. Comparing a fresh +12 draw against it would confound the twelve lines
# with the server process, which is exactly the confound that cost the import table one of its
# two control arms today. So the control is redrawn alongside the treatment.
set -uo pipefail
cd "$(dirname "$0")"

SRC="specs/jsoncodec.yaml"
INERT="specs/_inert_twelve_lines.txt"
VARIANT="specs/jsoncodec-grow.yaml"
CTL="./generated/jsoncodec-ctl"
GROW="./generated/jsoncodec-grow"
WANT_PID=4439
WANT_START="Wed Jul 29 09:29:40 2026"

PID=$(lsof -ti:8080 2>/dev/null | head -1)
[[ -z "$PID" ]] && { echo "REFUSING: nothing on :8080."; exit 4; }
START=$(ps -o lstart= -p "$PID" 2>/dev/null | sed 's/^ *//; s/ *$//')
if [[ "$PID" != "$WANT_PID" || "$START" != "$WANT_START" ]]; then
  echo "REFUSING: server is not the process the rest of today's controls were drawn on."
  echo "  want pid $WANT_PID '$WANT_START'; got pid $PID '$START'"
  echo "Both arms would still be internally consistent, but they would not be comparable to"
  echo "the taskflow and taskapipro arms, which is half the point."
  exit 5
fi
for d in "$CTL" "$GROW"; do
  [[ -d "$d" ]] && { echo "REFUSING: $d exists; this pair has been drawn."; exit 2; }
done
pgrep -f "\.venv/bin/guildlm-build" >/dev/null && { echo "REFUSING: a generation is in flight."; exit 3; }
SCHED=$(pgrep -fl '_sweep_v5.*\.sh|_run_queue.*\.sh|_chain_run\.sh|_inert_prose_draw\.sh|_pristine_pre_edit_draw\.sh|_taskflow_dose_draw\.sh|_jsoncodec_growth_test\.sh' | grep -v "^$$ " || true)
[[ -n "$SCHED" ]] && { echo "REFUSING: another scheduler is running:"; echo "$SCHED" | sed 's/^/  /'; exit 3; }
git diff --quiet HEAD -- "$SRC" || { echo "REFUSING: $SRC differs from HEAD."; exit 6; }

# ---- derive the variant --------------------------------------------------------------------
# THE ANCHOR IS THE ENTRY'S LAST LINE, not a phrase. jsoncodec's purpose is a FOLDED scalar,
# so YAML wraps it wherever it likes and no sentence is guaranteed to sit on one line — my
# first attempt keyed on "compare times with time.Time.Equal", which the file splits across
# lines 40 and 41 and grep therefore never matches. Anchoring on the entry's final line is
# both unique and stable against rewrapping.
ANCHOR="      time.Time.Equal, never ==). Standard library only."
[[ -z "$ANCHOR" ]] && { echo "REFUSING: anchor line not found."; exit 7; }
(( $(grep -cF "$ANCHOR" "$SRC") == 1 )) || { echo "REFUSING: anchor is not unique."; exit 8; }
(( $(grep -c '' "$INERT") == 12 )) || { echo "REFUSING: $INERT is not 12 lines."; exit 9; }

awk -v anchor="$ANCHOR" -v inert="$INERT" '
  { print }
  $0 == anchor { while ((getline line < inert) > 0) print line; close(inert) }
' "$SRC" > "$VARIANT"
A=$(diff "$SRC" "$VARIANT" | grep -c '^>' || true); R=$(diff "$SRC" "$VARIANT" | grep -c '^<' || true)
(( A == 12 && R == 0 )) || { echo "REFUSING: variant is +$A/-$R, need +12/-0."; rm -f "$VARIANT"; exit 10; }
.venv/bin/python - "$SRC" "$VARIANT" <<'PY' || { rm -f "$VARIANT"; exit 11; }
import sys, yaml
a=yaml.safe_load(open(sys.argv[1])); b=yaml.safe_load(open(sys.argv[2]))
assert sorted(a)==sorted(b) and [k for k in a if a[k]!=b.get(k)]==["files"], "wrong keys changed"
fa,fb=a["files"],b["files"]; assert len(fa)==len(fb)
d=[fa[i].get("path") for i in range(len(fa)) if fa[i]!=fb[i]]
assert d==["event_test.go"], f"expected only event_test.go to differ, got {d}"
print(f"  parse check OK: only {d[0]} differs")
PY
echo "spec OK · server OK: pid $PID"
[[ "${1:-}" == "--check" ]] && { echo "--check: guards pass. Not drawing."; exit 0; }

draw() {  # <spec> <out> <tag>
  local log="logs/jsoncodec-$3-$(date +%m%d%H%M).log"
  echo "=== jsoncodec $3 draw -> $2 (log $log) ==="
  SECONDS=0
  .venv/bin/guildlm-build main --spec "$1" --out "$2" \
    --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
    --base-url http://localhost:8080/v1 \
    --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
    --max-fix-rounds 5 > "$log" 2>&1
  echo "=== rc=$? (${SECONDS}s) ==="
  echo "$log"
}
LOG_CTL=$(draw "$SRC" "$CTL" ctl | tail -1)
LOG_GROW=$(draw "$VARIANT" "$GROW" grow | tail -1)

echo
echo "=== OUTCOME: control vs +12 inert lines, same server, back to back ==="
echo "Reference: taskflow +12 -> CODE 4 of 12 · taskapipro +12 -> CODE 3 of 7"
echo "           same-condition variance measured ZERO on both (0/8, 0/7, 0/12)"
.venv/bin/python _untouched_diff.py "$CTL" "$GROW" "$LOG_CTL" "$LOG_GROW"
