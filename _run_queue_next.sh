#!/usr/bin/env bash
# The two draws that today's findings created. Launch AFTER _run_queue_0728.sh prints its
# completion line and after _grade_0728.sh has been read.
#
# Same discipline as everything written today: REFUSE while another scheduler is running
# rather than park on `pgrep guildlm-build`. A queue spends minutes between jobs running
# `go test -race -count=4`, and in that window no build process exists while the corpus is
# still being written — waiting on the worker is how two generations end up on one GPU.
# --check runs the guards and generates nothing, because a script whose only mode is DO IT
# will eventually be run to find out what it would do.
set -uo pipefail
cd "$(dirname "$0")"
CHECK=0
[[ "${1:-}" == "--check" ]] && CHECK=1

SCHEDULERS=$(pgrep -fl '_run_queue.*\.sh|_sweep.*\.sh|_resweep.*\.sh|_rebuild_corpus\.sh|_chain_run\.sh|_shortener_mirrors_run\.sh' | grep -v "$$" || true)
if [[ -n "$SCHEDULERS" ]]; then
  echo "REFUSING: another scheduler is running. Sequence by hand:"
  echo "$SCHEDULERS" | sed 's/^/  /'
  exit 3
fi
if pgrep -f "guildlm-build main" > /dev/null; then
  echo "REFUSING: a generation is in flight."
  exit 3
fi

if (( CHECK )); then
  echo "--check: guards pass. Would draw taskapipro (draw 4) then workapi."
  exit 0
fi

echo "=== next queue starts $(date) ==="

# 1. taskapipro draw 4 carries THREE changes, each graded by a different probe so bundling
#    cannot blur a verdict:
#      a. the config WIRING — DefaultPageSize/MaxPageSize reach both handlers at last.
#         Graded by mutating `limit = h.defaultPageSize` / `h.maxPageSize` to 7777, and by
#         _dead_config.py reporting ZERO dead fields on the new tree. That second one is the
#         real verdict and no mutation gives it: the tool that found the gap has to go quiet
#         on the tree that fixed it.
#      b. Delete's own 404, the third instance of the same mirror found today. Graded by
#         StatusNotFound->StatusBadRequest on the Delete site, per line.
#      c. the config.go PROMISE repair — the entry now names all three Validate guards.
#         Graded by whether internal/config is green at all, which draw 3 was not: it burned
#         seven fix rounds on a test the implementation was never asked to satisfy.
echo
echo "############ taskapipro draw 4: config wiring + Delete-404 + the promise repair ############"
./_chain_run.sh taskapipro

# 2. workapi's Delete-404. Found by _reachability: the writeJSON(w, StatusNotFound, nil)
#    inside Delete is executed ZERO times by the whole suite while Get's identical line is
#    executed, and the spec's delete test asserts its 404 from the GET that follows a
#    SUCCESSFUL delete. Same hole as taskflow's, in a spec whose twin I closed on Monday.
echo
echo "############ workapi: Delete's own 404 ############"
./_chain_run.sh workapi

echo "=== next queue complete $(date) ==="
echo
echo "THEN, in order — each refuses if the previous is still running:"
echo "  ./_grade_0728.sh            # and the taskapipro/workapi probes above"
echo "  ./_resweep_v4.sh --check    # re-take the baseline with the repaired walk"
echo "  ./_sweep_v5.sh --check      # only after the baseline is re-taken"
