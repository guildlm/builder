#!/usr/bin/env bash
# ONE queue for the remaining closure runs, because four independent waiters is a race.
#
# MATCH THE EXECUTABLE, NOT A STRING ANY COMMAND LINE CAN CONTAIN. `pgrep -f
# "guildlm-build main"` also matches every shell whose own command line mentions it —
# including the `until ! pgrep -f "guildlm-build main"; do sleep; done` waiters this
# repo writes constantly. Two orphaned waiters of mine matched their own pattern and
# made _resweep_v4 refuse on a machine with nothing generating. The guard was right
# about its query and wrong about the world, which is the failure this whole session
# has been about. `.venv/bin/guildlm-build` is the path only the real process carries.
# Each closure script parks on `while pgrep -f "\.venv/bin/guildlm-build"; do sleep 30; done`.
# That is correct for one waiter and wrong for four: when taskflow's six-hour build
# finished, all four woke within the same 30-second window and only luck decided that a
# single one won. Two 6-hour generations sharing the GPU is the failure this project has
# already paid for once — a live build lost its files to a command run beside it.
#
# So: one process, one list, in order. Each script still parks on its own loop, which is
# now a no-op guard rather than the scheduler.
#
# ORDER IS BY INFORMATION PER HOUR, not by when the edit was written:
#   1. the four Chain specs — the N=5 replication, and the only result that answers a
#      question no single run can (same edit, five specs). taskflow already landed.
#   2. bitset — two closures, smallest spec in the corpus, minutes not hours.
#   3. shortener — two mirror closures, and the spec that pays in TIME, so it goes last.
set -uo pipefail
cd "$(dirname "$0")"

while pgrep -f "\.venv/bin/guildlm-build" > /dev/null; do sleep 30; done
echo "=== queue starts $(date) ==="

for spec in usersapi taskapi taskapipro workapi; do
  echo
  echo "############ chain: $spec ############"
  ./_chain_run.sh "$spec"
done

echo
echo "############ bitset witness ############"
./_bitset_witness_run.sh

echo
echo "############ shortener mirrors ############"
./_shortener_mirrors_run.sh

# taskflow LAST and appended after the queue was already running, because its closure run
# had already landed (RED, six hours) and its result is measured. This re-run carries three
# changes at once — a spec REPAIR (the TestWireFieldNames path/decode coupling that cost the
# last build), plus the Delete-404 and parsePage-clamp closures — and each is graded by a
# different mutation, so bundling them cannot blur a verdict. Six hours is the price of a
# taskflow draw; it goes behind everything that answers faster.
echo
echo "############ taskapipro: parser-clamp closure (draw 2) ############"
./_chain_run.sh taskapipro

echo
echo "############ taskflow: repair + two closures ############"
./_chain_run.sh taskflow
# tasks-api SECOND draw. Its two closures both held, but the run exposed a spec
# CONTRADICTION: the store interface was pinned as Create(t Task) error — a value, no
# return — while the handler entry requires the 201 body to carry the assigned id. No
# implementation satisfies both, and every draw resolved it the same wrong way. The
# interface is now Create(t *Task) error and TestCreate201 asserts the id.
echo
echo "############ tasks-api: pointer Create + id assertion ############"
./_tasksapi_empty_run.sh
echo "=== queue complete $(date) ==="
