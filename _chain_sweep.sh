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

while pgrep -f "guildlm-build main" > /dev/null; do sleep 30; done
echo "=== GPU free; starting chain closure sweep $(date) ==="

for spec in usersapi taskapi taskapipro workapi; do
  echo
  echo "############ $spec ############"
  ./_chain_run.sh "$spec"
done
echo "=== chain closure sweep complete $(date) ==="
