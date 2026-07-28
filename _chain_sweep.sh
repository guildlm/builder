#!/usr/bin/env bash
# Run the Chain closure for the four specs that are not taskflow, one at a time.
#
# ONE BUILD AT A TIME. Two generations sharing the GPU is how a run lost its files
# mid-write; the rebuild script waits for the same reason. taskflow is excluded because
# it is already running under _taskflow_chain_run.sh — this waits for it.
#
# taskapipro and workapi also carry a config closure in the same edit (a Validate guard
# that accepts zero), so their runs grade two invariants each.
set -uo pipefail
cd "$(dirname "$0")"

# MATCH THE EXECUTABLE, NOT A STRING ANY COMMAND LINE CAN CONTAIN. `pgrep -f
# "guildlm-build main"` also matches every shell whose own command line mentions it —
# including the `until ! pgrep -f "guildlm-build main"; do sleep; done` waiters this
# repo writes constantly. Two orphaned waiters of mine matched their own pattern and
# made _resweep_v4 refuse on a machine with nothing generating. The guard was right
# about its query and wrong about the world, which is the failure this whole session
# has been about. `.venv/bin/guildlm-build` is the path only the real process carries.
while pgrep -f "\.venv/bin/guildlm-build" > /dev/null; do sleep 30; done
echo "=== GPU free; starting chain closure sweep $(date) ==="

for spec in usersapi taskapi taskapipro workapi; do
  echo
  echo "############ $spec ############"
  ./_chain_run.sh "$spec"
done
echo "=== chain closure sweep complete $(date) ==="
