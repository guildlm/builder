#!/usr/bin/env bash
# Grade the two draws _run_queue_next.sh produces: taskapipro draw 4 and workapi.
#
# WHY A NEW FILE RATHER THAN EXTENDING _grade_0728.sh — and it is not organisation. That
# script's clamp probe matches `^(limit|offset)\s*=\s*(\d+)$`, i.e. an assignment of a
# NUMERIC LITERAL. The whole point of the config-wiring edit is that those literals become
# FIELDS:
#
#     if limit <= 0            { limit = h.defaultPageSize }
#     if limit > h.maxPageSize { limit = h.maxPageSize }
#
# The old regex matches neither. Pointed at draw 4 it would find the offset clamps, print
# them, and say nothing at all about the two sites the edit exists to create — a grader
# reporting rows while silently skipping the subject. That is the same shape as today's
# `glob` bug and today's clamp-family gap in the probe registry: the instrument could not
# express the mutation, so the question went unasked and the output looked complete.
set -uo pipefail
cd "$(dirname "$0")"

ready() {  # exists AND nothing is writing it
  local art="$1"
  [[ -d "$art" ]] || { echo "--- $art: NOT GENERATED YET ---"; return 1; }
  .venv/bin/python _corpus_state.py "$art" > /dev/null 2>&1 || {
    echo "--- $art: BEING WRITTEN RIGHT NOW — not graded ---"; return 1; }
  return 0
}

banner() {  # a red tree makes every row BASELINE-RED; say so before printing any
  local art="$1" mod
  mod=$(find "$art" -name go.mod 2>/dev/null | head -1)
  [[ -z "$mod" ]] && { echo "  (no go.mod — generation failed early)"; return; }
  if (cd "$(dirname "$mod")" && go test ./... > /dev/null 2>&1); then
    echo "  tree is GREEN — verdicts below are about the sites."
  else
    echo "  ** TREE IS NOT GREEN ** — BASELINE-RED rows below describe the TREE, not the site:"
    (cd "$(dirname "$mod")" && go test ./... 2>&1 | grep -E "^(ok|FAIL|---)" | sed 's/^/    /')
  fi
}

TP=generated/taskapipro-chain4
if ready "$TP"; then
  echo
  echo "======== $TP  the config wiring ========"
  banner "$TP"

  # THE REAL VERDICT FIRST, and no mutation gives it: the tool that found the gap has to go
  # quiet on the tree that fixed it. A CAUGHT mutation on the new lines proves a test
  # defends them; only this proves the values reach a request at all.
  echo "  -- _dead_config on the new tree (MUST report zero dead fields):"
  .venv/bin/python _dead_config.py "$TP" 2>&1 | tail -6

  echo "  -- clamp sites, per line, NUMERIC and FIELD assignments both:"
  .venv/bin/python - "$TP" <<'PY'
import pathlib, re, sys
sys.path.insert(0, ".")
from _hole_hunt import replace_at
from _teeth_suite import verdict_for
art = pathlib.Path(sys.argv[1])
# `limit = 100` AND `limit = h.defaultPageSize`. The second form is what the wiring edit
# creates and what the 0728 grader could not see.
SITE = re.compile(r"^(limit|offset)\s*=\s*(\d+|h\.\w+)$")
for rel in ("internal/api/tasks.go", "internal/api/projects.go"):
    src = art / rel
    if not src.exists():
        print(f"     {rel} ABSENT — find where List was written before reading anything in")
        continue
    print(f"     -- {rel}")
    hit = False
    for i, ln in enumerate(src.read_text().splitlines()):
        s = ln.strip()
        m = SITE.match(s)
        if not m or s.startswith("//"):
            continue
        hit = True
        v, _ = verdict_for(art, rel, replace_at(i, ln, ln.replace(f"= {m.group(2)}", "= 7777", 1)))
        print(f"        L{i+1:<4} {v:<10} {s[:44]}")
    if not hit:
        print(f"        NO clamp site matched in {rel} — if the wiring landed there must be")
        print(f"        `limit = h.defaultPageSize` and `limit = h.maxPageSize` here. Absent")
        print(f"        means the edit did NOT take, which is a result, not a clean row.")
print("     TARGET: h.defaultPageSize and h.maxPageSize sites CAUGHT on BOTH handlers.")
print("     The offset clamps must STAY CAUGHT (draw 3 closed them).")
PY

  echo "  -- Delete's own 404 (per line; Get's was already CAUGHT):"
  .venv/bin/python - "$TP" internal/api/tasks.go <<'PY'
import pathlib, sys
sys.path.insert(0, ".")
from _hole_hunt import replace_at
from _teeth_suite import verdict_for
art, rel = pathlib.Path(sys.argv[1]), sys.argv[2]
src = art / rel
if not src.exists():
    print(f"     {rel} ABSENT"); raise SystemExit(0)
for i, ln in enumerate(src.read_text().splitlines()):
    if "http.StatusNotFound" not in ln or ln.strip().startswith("//"):
        continue
    v, _ = verdict_for(art, rel, replace_at(i, ln,
        ln.replace("http.StatusNotFound", "http.StatusBadRequest", 1)))
    print(f"        L{i+1:<4} {v:<10} {ln.strip()[:52]}")
PY
fi

WA=generated/workapi-chain2
if ready "$WA"; then
  echo
  echo "======== $WA  Delete's own 404 ========"
  banner "$WA"
  echo "  -- per line; before the edit Get's 404 ran and Delete's was COLD:"
  .venv/bin/python - "$WA" internal/api/tasks.go <<'PY'
import pathlib, sys
sys.path.insert(0, ".")
from _hole_hunt import replace_at
from _teeth_suite import verdict_for
art, rel = pathlib.Path(sys.argv[1]), sys.argv[2]
src = art / rel
if not src.exists():
    print(f"     {rel} ABSENT"); raise SystemExit(0)
for i, ln in enumerate(src.read_text().splitlines()):
    if "http.StatusNotFound" not in ln or ln.strip().startswith("//"):
        continue
    v, _ = verdict_for(art, rel, replace_at(i, ln,
        ln.replace("http.StatusNotFound", "http.StatusBadRequest", 1)))
    print(f"        L{i+1:<4} {v:<10} {ln.strip()[:52]}")
PY
fi

# THE CHEAPER CONFIRMATION, and it should agree with the mutations above. A closed
# Delete-404 must no longer be COLD — one coverage run per tree, no mutation at all. If the
# mutation says CAUGHT and coverage still says COLD, one of them is wrong and that matters
# more than either verdict.
echo
echo "======== reachability re-run (COLD sites must have shrunk) ========"
for art in "$TP" "$WA"; do
  [[ -d "$art" ]] && .venv/bin/python _reachability.py "$art" 2>&1 | tail -8
done
echo
echo "Baseline for comparison: logs/reachability-rows.tsv (-v4 corpus, 60 COLD of 250)."
