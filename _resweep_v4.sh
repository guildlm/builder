#!/usr/bin/env bash
# Re-sweep the -v4 corpus with the repaired walk, and REPLACE the baseline.
#
# WHY THIS HAS TO RUN BEFORE THE v5 REDRAW, not after.
#
# The plan was: redraw the repaired specs as -v5, sweep both, diff. That plan is now wrong
# in a way that would have produced a spectacular and meaningless result. Five of the six
# mutation shapes walked `glob("*.go")` instead of `rglob`, so every artifact with an
# internal/ layout — ledger, taskapi, taskapipro, workapi — contributed zero status rows and
# zero error-wrapping rows. workapi alone goes from 6 rows to 36 once the walk is fixed.
#
# So a v4-vs-v5 diff taken now would show a large jump in rows and candidates, and NONE of
# it would be about the specs. It would be the tool fix, wearing the costume of a result.
#
#   When the instrument changes, the BASELINE has to be re-taken with the new instrument
#   before anything is compared. Otherwise the first thing the comparison measures is the
#   change to the instrument.
#
# Hence: re-sweep v4 first, with the fixed walk, and let THAT be the before.
#
# The previous rows are preserved as logs/hole-hunt-rows-before-walk-fix.tsv, matching the
# convention already used for -before-redraw and -before-noapply-fix. The live file is
# git-tracked precisely so this replacement shows up as a diff nobody has to remember to
# save.
#
# --all-sites because the recorded sweep used it: the tracked file holds several rows per
# (artifact, file, shape), which the default one-site-per-file walk cannot produce. Sweeping
# without it would shrink the baseline for a second, unrelated reason.
#
# EXPECT HOURS. Every row is a full go build + vet + test -race -count=4 on a mutated tree,
# the old sweep was 170 rows, and this one will be substantially larger.
set -uo pipefail
cd "$(dirname "$0")"
CHECK=0
[[ "${1:-}" == "--check" ]] && CHECK=1

SCHEDULERS=$(pgrep -fl '_run_queue.*\.sh|_sweep.*\.sh|_rebuild_corpus\.sh|_chain_run\.sh|_shortener_mirrors_run\.sh' | grep -v "$$" || true)
if [[ -n "$SCHEDULERS" ]]; then
  echo "REFUSING: a scheduler is running — the sweep would measure trees mid-write and"
  echo "compete with a generation for the machine:"
  echo "$SCHEDULERS" | sed 's/^/  /'
  exit 3
fi
# MATCH THE EXECUTABLE, NOT A STRING ANY COMMAND LINE CAN CONTAIN. `pgrep -f
# "guildlm-build main"` also matches every shell whose own command line mentions it —
# including the `until ! pgrep -f "guildlm-build main"; do sleep; done` waiters this
# repo writes constantly. Two orphaned waiters of mine matched their own pattern and
# made _resweep_v4 refuse on a machine with nothing generating. The guard was right
# about its query and wrong about the world, which is the failure this whole session
# has been about. `.venv/bin/guildlm-build` is the path only the real process carries.
if pgrep -f "\.venv/bin/guildlm-build" > /dev/null; then
  echo "REFUSING: a generation is in flight."
  exit 3
fi
if [[ ! -f logs/hole-hunt-rows-before-walk-fix.tsv ]]; then
  echo "REFUSING: logs/hole-hunt-rows-before-walk-fix.tsv is missing — the pre-fix rows are"
  echo "the only record of what the corpus said before the instrument changed, and this run"
  echo "overwrites the live file. Copy it first."
  exit 3
fi

if (( CHECK )); then
  echo "--check: guards pass. Would sweep every generated/*-v4 tree with --all-sites and"
  echo "replace logs/hole-hunt-rows.tsv ($(wc -l < logs/hole-hunt-rows.tsv) rows today)."
  exit 0
fi

LOG="logs/resweep-v4-$(date +%m%d%H%M).log"
echo "=== v4 re-sweep with the repaired walk starts $(date) -> $LOG ==="
.venv/bin/python _hole_hunt.py --all-sites > "$LOG" 2>&1
RC=$?
echo "=== done rc=$RC $(date) ==="
tail -30 "$LOG"

echo
echo "=== rows: before the walk fix vs after ==="
echo "  before: $(wc -l < logs/hole-hunt-rows-before-walk-fix.tsv)"
echo "  after : $(wc -l < logs/hole-hunt-rows.tsv)"
echo
echo "The DIFFERENCE IS NOT A RESULT ABOUT THE CORPUS. It is the size of what five shapes"
echo "were never asked. Read the coverage block in the log: any 'NOT PROBED' line that"
echo "survives this fix is a shape still under-sampling, and that is the number to chase."
echo
echo "Then, and only then, the redraw:  ./_sweep_v5.sh --check"
echo
echo "THE OTHER BASELINE DOES NOT NEED RE-TAKING, and this was checked rather than assumed:"
echo "logs/reachability-rows.tsv (250 sites, 60 cold) comes from _reachability, which imports"
echo "go_files from _hole_hunt — so it would have inherited the glob bug. Git order settles it:"
echo "the walk fix (c05bc95) landed BEFORE _reachability was written (694d500) and before its"
echo "rows were dumped (034b1a6). That baseline was taken with the repaired walk."
echo
echo "The rule that prompted the check is the point: when an instrument changes, EVERY number"
echo "taken with it is suspect until its date is compared, not just the one you were looking at."
