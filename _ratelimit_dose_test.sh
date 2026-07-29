#!/usr/bin/env bash
# THE CAMPAIGN'S REAL DOSE: 48 inert lines into a spec nobody edited, both arms, one server.
#
# Design and branches: logs/PREDICTION-does-the-campaigns-real-dose-move-a-verdict.txt
#
# 48 lines = the tracked twelve-line inert block in FOUR entries. That is inside the campaign's
# 43-73 range AND spread across entries the way the campaign actually grew specs. The four
# entries deliberately EXCLUDE api.go and middleware.go, which carry every measured mutation
# row, so any verdict change is collateral rather than aimed.
set -uo pipefail
cd "$(dirname "$0")"

SRC="specs/ratelimit.yaml"
INERT="specs/_inert_twelve_lines.txt"
VARIANT="specs/ratelimit-dose.yaml"
CTL="./generated/ratelimit-ctl"
DOSE="./generated/ratelimit-dose"
TARGETS="bucket.go registry.go main.go ratelimit_test.go"
WANT_PID=4439
WANT_START="Wed Jul 29 09:29:40 2026"

PID=$(lsof -ti:8080 2>/dev/null | head -1)
[[ -z "$PID" ]] && { echo "REFUSING: nothing on :8080."; exit 4; }
START=$(ps -o lstart= -p "$PID" 2>/dev/null | sed 's/^ *//; s/ *$//')
[[ "$PID" == "$WANT_PID" && "$START" == "$WANT_START" ]] || {
  echo "REFUSING: server is not the process today's other arms used."
  echo "  want pid $WANT_PID '$WANT_START'; got pid $PID '$START'"; exit 5; }
for d in "$CTL" "$DOSE"; do [[ -d "$d" ]] && { echo "REFUSING: $d exists."; exit 2; }; done
pgrep -f "\.venv/bin/guildlm-build" >/dev/null && { echo "REFUSING: generation in flight."; exit 3; }
SCHED=$(pgrep -fl '_sweep_v5.*\.sh|_run_queue.*\.sh|_chain_run\.sh|_inert_prose_draw\.sh|_pristine_pre_edit_draw\.sh|_taskflow_dose_draw\.sh|_jsoncodec_growth_test\.sh|_ratelimit_dose_test\.sh' | grep -v "^$$ " || true)
[[ -n "$SCHED" ]] && { echo "REFUSING: another scheduler running:"; echo "$SCHED" | sed 's/^/  /'; exit 3; }
git diff --quiet HEAD -- "$SRC" || { echo "REFUSING: $SRC differs from HEAD."; exit 6; }
(( $(grep -c '' "$INERT") == 12 )) || { echo "REFUSING: $INERT is not 12 lines."; exit 7; }

# ---- build the variant STRUCTURALLY, not by text anchor ------------------------------------
# Every ratelimit entry's purpose ends with the same sentence ("Standard library only."), so a
# text anchor is not unique — the jsoncodec run already cost one attempt to a folded scalar and
# a bogus uniqueness check. Insert before the NEXT `  - path:` line instead: structural,
# unique by construction, and indifferent to how YAML wrapped the prose.
.venv/bin/python _mkvariant_ratelimit.py "$SRC" "$VARIANT" "$INERT" $TARGETS || exit 8
A=$(diff "$SRC" "$VARIANT" | grep -c '^>' || true); R=$(diff "$SRC" "$VARIANT" | grep -c '^<' || true)
(( A == 48 && R == 0 )) || { echo "REFUSING: variant is +$A/-$R, need +48/-0."; rm -f "$VARIANT"; exit 9; }
.venv/bin/python - "$SRC" "$VARIANT" <<'PY' || { rm -f "$VARIANT"; exit 10; }
import sys, yaml
a=yaml.safe_load(open(sys.argv[1])); b=yaml.safe_load(open(sys.argv[2]))
assert [k for k in a if a[k]!=b.get(k)]==["files"]
fa,fb=a["files"],b["files"]; assert len(fa)==len(fb)
d=[fa[i]["path"] for i in range(len(fa)) if fa[i]!=fb[i]]
assert set(d)=={"bucket.go","registry.go","main.go","ratelimit_test.go"}, f"wrong entries: {d}"
assert all(fa[i]==fb[i] for i in range(len(fa)) if fa[i]["path"] in ("api.go","middleware.go")), \
       "api.go/middleware.go MUST be untouched — they carry every measured row"
print(f"  parse check OK: exactly {sorted(d)} differ; api.go and middleware.go identical")
PY
echo "spec OK (+48/-0) · server OK: pid $PID"
[[ "${1:-}" == "--check" ]] && { echo "--check: guards pass. Not drawing."; exit 0; }

draw() {
  local log="logs/ratelimit-$3-$(date +%m%d%H%M).log"
  echo "=== ratelimit $3 -> $2 (log $log) ==="; SECONDS=0
  .venv/bin/guildlm-build main --spec "$1" --out "$2" \
    --model mlx-community/Qwen2.5-Coder-7B-Instruct-4bit \
    --base-url http://localhost:8080/v1 \
    --candidates 2 --examples examples/verified_contracts.jsonl --shots 2 \
    --max-fix-rounds 5 > "$log" 2>&1
  echo "=== rc=$? (${SECONDS}s) ==="; echo "$log"
}
LC=$(draw "$SRC" "$CTL" ctl | tail -1)
LD=$(draw "$VARIANT" "$DOSE" dose | tail -1)
echo
echo "=== FILES: control vs +48 ==="
.venv/bin/python _untouched_diff.py "$CTL" "$DOSE" "$LC" "$LD"
echo
echo "=== VERDICTS: sweeping both arms ==="
.venv/bin/python _hole_hunt.py --all-sites "$CTL"  2>&1 | grep -E "^ratelimit-ctl"  || true
echo "  ---"
.venv/bin/python _hole_hunt.py --all-sites "$DOSE" 2>&1 | grep -E "^ratelimit-dose" || true
