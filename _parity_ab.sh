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

# THE HARNESS MUST NOT MOVE UNDER A MULTI-HOUR RUN. Every draw is a fresh `guildlm-build`
# process that re-reads src/builder.py, so an edit landing mid-run puts some draws on one
# harness and the rest on another — and the whole design of a paired A/B is that control and
# arm share a commit. On 31 July this nearly happened: a one-line logging change was queued,
# would have been applied between pairs, and was caught only because I stopped to check.
#
# HASHED, NOT `git rev-parse HEAD`. Measured the same day: appending a line to src/builder.py
# leaves HEAD unchanged and changes the file. A HEAD guard would have missed exactly the edit
# it was written to catch. `git status --porcelain` catches THAT case but answers "is the tree
# dirty", not "is it what I started with" — a file edited and reverted to a different commit's
# content reads clean and is wrong.
#
# EVERY INPUT A DRAW READS, not just the code. Measured after the guard was first written with
# two files: a draw also reads $SPEC and $EXAMPLES, and the spec is the MOST-EDITED file in this
# campaign — 191 edits on record, against a handful for the runner. Guarding builder.py while
# leaving the spec free would have watched the quiet door and left the busy one open.
HARNESS_FILES=(src/builder.py "$0" "$SPEC" "$EXAMPLES")
harness_hash () { shasum "${HARNESS_FILES[@]}" | awk '{print $1}' | tr -d '\n'; }
WANT_HARNESS=$(harness_hash)

echo "=== parity A/B · $PAIRS pairs · spec=$SPEC · server pid=$WANT_PID · $(date) ==="
echo "=== harness locked at ${WANT_HARNESS:0:16} (${#HARNESS_FILES[@]} files: builder, runner, spec, examples) ==="

draw () {   # draw <out> <log> <enable_rules>
  local out="$1" log="$2" rules="$3"
  local pid; pid=$(./_server_pid.sh) || return 4
  [[ "$pid" == "$WANT_PID" ]] || { echo "REFUSING: server pid changed $WANT_PID -> $pid"; return 5; }
  local now; now=$(harness_hash)
  [[ "$now" == "$WANT_HARNESS" ]] || {
    echo "REFUSING: the harness changed mid-run (${WANT_HARNESS:0:16} -> ${now:0:16})."
    echo "  Draws already taken used the OLD harness; continuing would split this experiment"
    echo "  across two versions of the code. Restart the run, or revert src/builder.py."
    return 6; }
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
echo "    store.go must NOT declare MemStore, and memory.go must not be empty."
.venv/bin/python - "$PAIRS" <<'PY'
import pathlib, re, sys
pairs = int(sys.argv[1])
decl = re.compile(r"^\s*type\s+MemStore\b|^\s*func\s+\(\w+\s+\*?MemStore\)", re.M)
def grade(tree):
    d = pathlib.Path("generated")/tree
    s, m = d/"internal/store/store.go", d/"internal/store/memory.go"
    if not s.exists() or not m.exists():
        return "NO TREE", "", ""
    st, mm = s.read_text(), m.read_text()
    split_ok = not decl.search(st) and bool(decl.search(mm))
    return ("SPLIT" if split_ok else "CONSOLIDATED"), f"{len(st)}B", f"{len(mm)}B"
print(f"  {'pair':6s} {'control':>34s}    {'arm':>34s}")
for i in range(1, pairs + 1):
    cv, cs, cm = grade(f"ledger-parity-ctl-{i}")
    av, as_, am = grade(f"ledger-parity-arm-{i}")
    print(f"  {i:<6d} {cv:>14s} store={cs:>7s} mem={cm:>7s}    {av:>14s} store={as_:>7s} mem={am:>7s}")
print("\n  Read the pre-registration before reading this table: the arm was predicted to SPLIT on")
print("  at least 2 of 3, at only 45%, because the implementer file gets the same clause and")
print("  already resists it. A null here does NOT revive 'the model cannot split a package'.")
PY
