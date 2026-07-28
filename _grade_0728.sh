#!/usr/bin/env bash
# Grade today's four closure runs. Separate from _grade_closures.sh on purpose: that script
# grades yesterday's artifacts and every verdict_for call runs a full `go test` suite, so
# re-running it to reach four new rows would cost twenty minutes to learn nothing new.
#
# Every block is PER LINE, never per shape. The same `offset = 0` text has five sites in one
# handler and three of them were already CAUGHT before today's edit — a shape-level grade
# would answer about whichever site comes first and read like an answer about the one I
# edited. Baselines are printed next to each verdict so a row that did not move is visible
# as a row that did not move.
#
# Absent artifacts are PRINTED as absent. "0 failures" over 0 graded artifacts reads exactly
# like success, which is how a silent skip becomes a claim.
set -uo pipefail
cd "$(dirname "$0")"

echo "=== grading $(date) ==="

# ASK BEFORE MEASURING. The first run of this script graded taskapipro-chain3 while the
# build was still writing it: the DIRECTORY existed, so the `-d` test passed, the handler
# files did not exist yet, and every block printed the message I had written for a draw that
# put its declarations in a different file. A half-written tree does not look absent — it
# looks like a finding, in the exact words of a finding I had already had. Every other
# instrument in this repo asks _corpus_state first; this one skipped it on its first draft,
# which is the whole reason the tool exists.
ready() {  # <artifact> -> 0 if it exists AND nothing is writing it
  local art="$1"
  [[ -d "$art" ]] || return 1
  if ! .venv/bin/python _corpus_state.py "$art" > /dev/null 2>&1; then
    echo "--- $art: BEING WRITTEN RIGHT NOW — not graded (a partial tree survives every"
    echo "    mutation, and 'no test file' is indistinguishable from 'no test'). ---"
    return 1
  fi
  return 0
}

# ---- 1. taskapipro draw 3: the mirrored projects clamp ------------------------------
# Baseline, measured per line on draw 2 BEFORE the edit:
#   tasks.go     L54 SURVIVED(inert)  L59 CAUGHT  L63 CAUGHT  L67 SURVIVED(inert)  L71 SURVIVED
#   projects.go  L53 SURVIVED(inert)  L58 CAUGHT  L62 SURVIVED  <- the target  L66/L70 SURVIVED
# The inert ones are masked by the guard that follows them (a limit of 0 or 7777 both end up
# clamped to 100), and L71/L70 is the max-page cap, which needs 100+ items to observe at all.
# Neither is what this edit is about; both are printed so the target is read in context.
if ready generated/taskapipro-chain3; then
  echo
  echo "======== generated/taskapipro-chain3  probe=clamp value (per line) ========"
  .venv/bin/python - <<'PY'
import pathlib, re, sys
sys.path.insert(0, ".")
from _hole_hunt import replace_at
from _teeth_suite import verdict_for
art = pathlib.Path("generated/taskapipro-chain3")
for rel in ("internal/api/tasks.go", "internal/api/projects.go"):
    src = art / rel
    if not src.exists():
        print(f"  {rel} ABSENT — the draw put these declarations somewhere else; find the")
        print(f"     file that holds them before reading anything into this line. Go does")
        print(f"     not care which file a func lives in, and workapi already moved one.")
        continue
    print(f"  -- {rel}")
    for i, ln in enumerate(src.read_text().splitlines()):
        s = ln.strip()
        if s.startswith("//"):
            continue
        m = re.match(r"^(limit|offset)\s*=\s*(\d+)$", s)
        if not m:
            continue
        v, _ = verdict_for(art, rel, replace_at(i, ln, ln.replace(f"= {m.group(2)}", "= 7777", 1)))
        print(f"     L{i+1:<4} {v:<10} {s[:40]}")
print("  TARGET: projects.go's `offset = 0` under `if offset < 0` must move SURVIVED -> CAUGHT.")
print("  The tasks.go pair must STAY CAUGHT — draw 2 won two clamps and silently lost a third.")
PY
elif [[ ! -d generated/taskapipro-chain3 ]]; then
  echo "--- generated/taskapipro-chain3: NOT GENERATED YET (probe=clamp value) ---"
fi

# ---- 2 + 3. the empty-list closures: usersapi, then taskapi's TWO collections -------
# Graded by the nil-slice mutation, not a boundary: `make([]T, 0, n)` -> `var out []T` is the
# one-line change that turns the body from [] into null with every length check still passing.
grade_nil() {  # <artifact> <relative go file> <label>
  local art="$1" rel="$2" label="$3"
  if ! ready "$art"; then
    [[ -d "$art" ]] || echo "--- $art: NOT GENERATED YET (probe=nil-slice, $label) ---"
    return
  fi
  echo
  echo "======== $art  probe=nil-slice  $label ========"
  .venv/bin/python - "$art" "$rel" <<'PY'
import pathlib, re, sys
sys.path.insert(0, ".")
from _hole_hunt import replace_at
from _teeth_suite import verdict_for
art, rel = pathlib.Path(sys.argv[1]), sys.argv[2]
src = art / rel
if not src.exists():
    print(f"  {rel} ABSENT — not a verdict about the closure; find where List was written.")
    raise SystemExit(0)
lines = src.read_text().splitlines()
hit = False
for i, ln in enumerate(lines):
    m = re.search(r"(\w+)\s*:=\s*make\(\[\](\S+?),\s*0", ln)
    if not m or ln.strip().startswith("//"):
        continue
    hit = True
    v, _ = verdict_for(art, rel, replace_at(i, ln, f"{ln[:len(ln)-len(ln.lstrip())]}var {m.group(1)} []{m.group(2)}"))
    print(f"  L{i+1:<4} {v:<10} {ln.strip()[:60]}")
if not hit:
    print(f"  NO `make([]T, 0, ...)` in {rel} — the guard this closure defends is not there.")
    print(f"  That is a finding, not a pass: either the list is built another way (check")
    print(f"  whether it can still emit null) or the file moved.")
PY
}

grade_nil generated/usersapi-chain2 store.go                     "usersapi: users"
grade_nil generated/taskapi-chain2  internal/store/memory.go     "taskapi: tasks AND projects (two make lines, L46/L87 in draw 1)"

# ---- 4. shortener re-run: the race closure, then the two mirrors --------------------
# The race is NOT graded by a mutation. Resolve took an RLock and wrote through it; the
# assertion is `-race` itself, so the grade is "does the detector stay quiet under a test
# that actually concurrently resolves". No test in the corpus did, which is why -race was
# green over a confirmed race for as long as it was.
SH=""
for cand in generated/shortener-mirrors3 generated/shortener-mirrors4; do
  ready "$cand" && SH="$cand"
done
if [[ -n "$SH" ]]; then
  echo
  echo "======== $SH  probe=race + 400/404 mirrors ========"
  echo "  -- was the concurrency test written at all?"
  grep -rl "TestResolveIsSafeUnderConcurrency" "$SH" 2>/dev/null | sed 's/^/     named in: /' \
    || echo "     NOT WRITTEN — the closure did not take; the race is undefended again"
  echo "  -- does Resolve still write under a read lock?"
  grep -n -A12 "func.*Resolve" "$SH"/store.go 2>/dev/null | grep -E "RLock|s\.m\[" | sed 's/^/     /'
  echo "  -- race detector, 4 runs:"
  ( cd "$SH" && go test -race -count=4 ./... 2>&1 | tail -8 | sed 's/^/     /' )
elif [[ ! -d generated/shortener-mirrors3 ]]; then
  echo "--- generated/shortener-mirrors3: NOT GENERATED YET (probe=race + mirrors) ---"
fi

echo
echo "=== grading complete $(date) ==="
