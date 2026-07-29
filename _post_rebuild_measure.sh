#!/usr/bin/env bash
# The measurement the corpus deletion forced: a FULL REDRAW comparison.
#
# Every -v4 tree was regenerated from the same specs with the same model a week after the
# originals, so the question the durability programme had answered for two specs of five —
# "do the closures survive the next regeneration?" — is now answerable for all of them at
# once. Runs only after the queue is empty, because a sweep over a moving corpus reads
# half-written trees (_corpus_state.py, and the usersapi verdicts that taught it).
set -uo pipefail
cd "$(dirname "$0")"

# THREE DEFECTS FIXED 29 JULY, all in the first fifteen lines of this script.
#
# 1. `guildlm-build main` MATCHES SHELLS THAT MERELY MENTION IT. This repo writes
#    `until ! pgrep -f "guildlm-build main"` waiters constantly, and each one carries the
#    string in its own argv — so this loop would wait forever on another waiter that is
#    itself waiting. Match `.venv/bin/guildlm-build`, the path only the real process has.
#
# 2. THE SCHEDULER LIST WAS STALE. It named _sweep.sh and _rebuild_corpus.sh; the schedulers
#    that exist now are _sweep_v5*.sh, _run_queue*.sh, _chain_run.sh and _inert_prose_draw.sh.
#    A queue spends real minutes BETWEEN jobs running `go test -race`, and in that window no
#    guildlm-build exists while the corpus is very much still being written — so waiting on
#    the worker alone wakes in the gap and sweeps a moving corpus. That is the failure
#    _corpus_state.py and the usersapi verdicts were written about.
#
# 3. AND IT IS NOT A WAITER'S JOB TO DECIDE THIS. Kept as a waiter because that is what this
#    script is, but the refusal below is what actually protects the evidence.
while pgrep -f "\.venv/bin/guildlm-build" > /dev/null || \
      pgrep -f '_sweep(_v5)?(_finish|_ledger)?\.sh|_run_queue.*\.sh|_rebuild_corpus\.sh|_chain_run\.sh|_inert_prose_draw\.sh' | grep -qv "^$$\$"; do
  sleep 60
done
echo "=== queue empty; post-rebuild measurement $(date) ==="

# PRESERVE THE BASELINE BEFORE THE SWEEP OVERWRITES IT. _hole_hunt rewrites
# logs/hole-hunt-rows.tsv on every whole-corpus run, and that file IS the record of what
# the pre-deletion corpus said — the only one, since generated/ is gitignored. Copy it to a
# tracked name first; without this the comparison destroys its own left-hand side.
# NEVER OVERWRITE A TRACKED BASELINE. This line existed to PRESERVE the pre-redraw rows and
# it would DESTROY them on a second run: logs/hole-hunt-rows-before-redraw.tsv has been
# tracked since 26 July and is the only surviving record of what the pre-deletion corpus
# said, because generated/ is gitignored. A script whose stated purpose is "preserve the
# baseline before the sweep overwrites it" that silently overwrites the preserved copy is
# the corpus-deletion shape with a smaller blast radius and a more reassuring comment.
if [[ -e logs/hole-hunt-rows-before-redraw.tsv ]]; then
  echo "REFUSING: logs/hole-hunt-rows-before-redraw.tsv already exists."
  echo "It is TRACKED and it is the only record of the pre-redraw corpus — generated/ is"
  echo "gitignored, so there is nothing to re-derive it from. Copying over it would destroy"
  echo "the left-hand side of the comparison this script exists to make."
  echo "If a NEW baseline is genuinely wanted, give it a new name and say why in the commit."
  exit 2
fi
cp logs/hole-hunt-rows.tsv logs/hole-hunt-rows-before-redraw.tsv
echo "baseline preserved -> logs/hole-hunt-rows-before-redraw.tsv"

echo "=== sweeping the rebuilt corpus (all sites) ==="
.venv/bin/python _hole_hunt.py --all-sites > logs/hole-hunt-after-redraw.log 2>&1
HUNT_RC=$?
echo "rc=$HUNT_RC  (rows rewritten in logs/hole-hunt-rows.tsv)"
tail -12 logs/hole-hunt-after-redraw.log
# ABORT IF THE SWEEP DID NOT RUN. _hole_hunt now exits 2 rather than sweeping a corpus that
# is still being written — and if it refuses, the rows file still holds the BASELINE, so the
# diff below would compare the baseline against itself and print "0 flips". A comparison
# that silently answers about nothing is precisely what this whole afternoon was spent
# closing; it does not get to happen in the script that reports the result.
if [[ $HUNT_RC -ne 0 ]]; then
  echo "ABORTING: the sweep did not run (rc=$HUNT_RC), so the rows file is unchanged."
  echo "A diff now would compare the baseline with itself and report no change."
  exit 1
fi

echo
echo "=== REDRAW DIFF: what a full regeneration changed ==="
.venv/bin/python _redraw_diff.py logs/hole-hunt-rows-before-redraw.tsv logs/hole-hunt-rows.tsv \
  | tee logs/redraw-diff.txt

echo
echo "=== registry scoreboard on the rebuilt corpus ==="
.venv/bin/python _teeth_suite.py 2>&1 | tail -25

echo
echo "=== per-site sort control (taskapi was rebuilt too, so re-verify the control) ==="
.venv/bin/python - <<'PY'
import sys, pathlib
sys.path.insert(0, ".")
from _teeth_suite import verdict_for, _reverse_id_sort_site
for tree, rel in (("generated/taskapi-v4", "internal/store/memory.go"),
                  ("generated/taskflow-v4", "store.go")):
    p = pathlib.Path(tree)
    if not (p / rel).exists():
        print(f"{tree}: {rel} not present"); continue
    for k in (1, 2):
        print(f"{tree:<28} site {k}: {verdict_for(p, rel, _reverse_id_sort_site(k, 2))[0]}")
PY
