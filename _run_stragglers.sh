#!/usr/bin/env bash
# The stragglers, in a NEW file because the running queue never saw them.
#
# _run_queue.sh was patched with an atomic write-temp-then-rename while it was live. That is
# the right way to avoid handing bash a half-written script — and it is exactly why the edit
# had no effect: rename swaps the INODE, and the running process keeps reading the file
# descriptor it already opened. So it finished the list it started with, and taskapipro's
# second draw was silently skipped. Atomic replace protects the reader from corruption and
# guarantees the reader never sees the change.
set -uo pipefail
cd "$(dirname "$0")"
while pgrep -f "guildlm-build main" > /dev/null; do sleep 30; done
echo "=== stragglers queue starts $(date) ==="
echo "############ taskapipro: parser-clamp closure (draw 2) ############"
./_chain_run.sh taskapipro
echo
echo "############ shortener: Resolve lock + concurrency test (draw 2) ############"
./_shortener_mirrors_run.sh
echo "=== stragglers complete $(date) ==="
