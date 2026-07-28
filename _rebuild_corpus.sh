#!/usr/bin/env bash
# Rebuild the -v4 reference corpus I deleted (FINDING-i-deleted-the-corpus.txt).
#
# _sweep.sh -> _ab_run.sh writes exactly ./generated/<spec>-v4, which is what the archive
# was, on the base model at :8080 — the same shape the originals were built with. These
# will be TODAY's model output, not the historical trees: the mutation registry pins exact
# strings lifted from the old artifacts, so expect NOAPPLY rows until they are re-pinned by
# shape. A fresh tree beats an empty directory; a re-pinned mutation beats a silent SKIP.
#
# Waits for any generation already in flight (the taskflow closure run) so two builds never
# share the GPU — and because a destructive-or-heavy command run against a live build is
# what caused the loss in the first place.
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
echo "=== GPU free; starting corpus rebuild $(date) ==="

# Highest instrument value first: the HTTP specs carry the teeth registry, the hole-hunt
# rows and every closure graded this week. Libraries after — cheap, and mostly single-file.
export GUILDLM_SWEEP_LOG="logs/rebuild-corpus-$(date +%m%d%H%M).log"
./_sweep.sh shortener tasks-api taskflow ratelimit usersapi jsonapi kvservice logstats \
            taskapi bitset walkv workerpool lrucache priorityqueue numkit genericset \
            jsoncodec eventbus expreval demo-small
echo "=== corpus rebuild complete $(date) ==="
grep -E "^RESULT " "$GUILDLM_SWEEP_LOG" | sort
