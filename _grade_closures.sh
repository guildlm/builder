#!/usr/bin/env bash
# Grade every boundary closure that has finished generating.
#
# Nine closures across seven artifacts, each graded with the SHAPE that found the hole and
# the FILE it lives in — the two things _hole_closed makes you state because getting either
# wrong reports a hole closed on a site nobody touched.
#
# Skips artifacts that are not there yet, so it can be run while the sweep is still going;
# _hole_closed itself refuses any tree that is being written. Grades nothing silently: an
# absent artifact is printed as absent, because "0 failures" over 0 graded artifacts reads
# exactly like success.
set -uo pipefail
cd "$(dirname "$0")"

grade() {  # <artifact> <spec> <probe> <file>
  local art="$1" spec="$2" probe="$3" file="$4"
  if [[ ! -d "$art" ]]; then
    echo "--- $art: NOT GENERATED YET (probe=$probe) ---"
    return
  fi
  echo
  echo "======== $art  probe=$probe  file=$file ========"
  .venv/bin/python _hole_closed.py "$art" "$spec" "--probe=$probe" "--file=$file"
}

grade generated/taskflow-chain   taskflow   chain-loop        middleware.go
grade generated/usersapi-chain   usersapi   chain-loop        middleware.go
grade generated/taskapi-chain    taskapi    chain-loop        internal/api/middleware.go
grade generated/taskapipro-chain taskapipro chain-loop        internal/api/middleware.go
grade generated/workapi-chain    workapi    chain-loop        internal/api/middleware.go

grade generated/workapi-chain    workapi    queue-size        internal/config/config.go
grade generated/taskapipro-chain taskapipro default-page-size internal/config/config.go

grade generated/bitset-witness   bitset     bitset-test       bitset.go
grade generated/bitset-witness   bitset     bitset-clear      bitset.go

# The empty-list closure. Graded by the nil-slice mutation, not by the boundary shape:
# `make([]Task, 0, n)` -> `var out []Task`, which is the one-line change that turns the
# response body from [] into null with every existing assertion still passing.
if [[ -d generated/tasksapi-empty ]]; then
  echo
  echo "======== generated/tasksapi-empty  probe=nil-slice ========"
  .venv/bin/python - <<'PY'
import pathlib, sys
sys.path.insert(0, "/Users/fatihturker/Desktop/Personal/Dev/guildlm/builder")
from _bound_probe import nil_slice
from _teeth_suite import verdict_for
art = pathlib.Path("generated/tasksapi-empty")
v, note = verdict_for(art, "store.go", nil_slice(0))
print(f"  nil-slice on store.go -> {v}   [was SURVIVED before the spec edit]")
print(f"  {note}")
PY
else
  echo "--- generated/tasksapi-empty: NOT GENERATED YET (probe=nil-slice) ---"
fi

# The tasks-api mirror closures, graded per LINE because a tag is not an address: the same
# `StatusBadRequest -> StatusNotFound` shape has eight sites in handlers.go and three of them
# were already CAUGHT before this edit.
if [[ -d generated/tasksapi-empty ]]; then
  echo
  echo "======== generated/tasksapi-empty  probe=400-mirrors (per line) ========"
  .venv/bin/python - <<'PY'
import pathlib, sys
sys.path.insert(0, "/Users/fatihturker/Desktop/Personal/Dev/guildlm/builder")
from _hole_hunt import replace_at
from _teeth_suite import verdict_for
art = pathlib.Path("generated/tasksapi-empty")
src = art / "handlers.go"
if not src.exists():
    print("  handlers.go absent — nothing graded")
    raise SystemExit(0)
lines = src.read_text().splitlines()
for i, ln in enumerate(lines):
    if "http.StatusBadRequest" not in ln or ln.strip().startswith("//"):
        continue
    mut = replace_at(i, ln, ln.replace("http.StatusBadRequest", "http.StatusNotFound", 1))
    v, _ = verdict_for(art, "handlers.go", mut)
    print(f"  L{i+1:<4} {v:<10} {ln.strip()[:66]}")
print("  before the edit: L24/L28/L80 CAUGHT, L33/L52/L71/L76/L99 SURVIVED")
print("  L33 is a DEAD SITE (the store's Title=='' guard is subsumed by Validate's")
print("  TrimSpace check) and is expected to stay SURVIVED.")
PY
fi

# shortener's two mirrors, per LINE: handlers.go has three StatusBadRequest sites (two were
# already CAUGHT) and two StatusNotFound sites (one already CAUGHT), so a shape-level grade
# would answer about whichever comes first.
if [[ -d generated/shortener-mirrors ]]; then
  echo
  echo "======== generated/shortener-mirrors  probe=400/404 mirrors (per line) ========"
  .venv/bin/python - <<'PY'
import pathlib, sys
sys.path.insert(0, "/Users/fatihturker/Desktop/Personal/Dev/guildlm/builder")
from _hole_hunt import replace_at
from _teeth_suite import verdict_for
art = pathlib.Path("generated/shortener-mirrors")
src = art / "handlers.go"
if not src.exists():
    print("  handlers.go absent — nothing graded")
    raise SystemExit(0)
lines = src.read_text().splitlines()
for old, new in (("http.StatusBadRequest", "http.StatusNotFound"),
                 ("http.StatusNotFound", "http.StatusBadRequest")):
    print(f"  -- {old} -> {new}")
    for i, ln in enumerate(lines):
        if old not in ln or ln.strip().startswith("//"):
            continue
        v, _ = verdict_for(art, "handlers.go", replace_at(i, ln, ln.replace(old, new, 1)))
        print(f"     L{i+1:<4} {v:<10} {ln.strip()[:58]}")
print("  before the edit: the ParseRequestURI 400 and the Stats 404 were the only SURVIVORs")
PY
fi
