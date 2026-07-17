#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")"
# Wait for the mutex-intra run to release the server, then test the gate on a
# fresh shortener build. No parallel generation — one server process.
while ps -p 56556 >/dev/null 2>&1; do sleep 30; done
echo "mutex-intra freed the server at $(date +%H:%M) — launching shortener+gate"
LOG="logs/shortener-gate-$(date +%m%d%H%M).log"
./_ab_run.sh shortener > "$LOG" 2>&1
KEEP="./generated/_shortener-GATE"; rm -rf "$KEEP"; cp -r ./generated/shortener-v4 "$KEEP" 2>/dev/null
# The three questions the prediction named, answered in the log:
{
  echo "########## SHORTENER + GATE RESULT ##########"
  grep -hE "RESULT shortener|COVERAGE shortener|re-locks a mutex|rejected .*candidate|best-of-N.*shortener|no clean candidate" "$LOG" | tail -20
  echo "--- Resolve() lock calls in the shipped artifact:"
  awk '/func \(s \*MemStore\) Resolve/,/^}/' "$KEEP"/store.go 2>/dev/null | grep -nE "RLock|Lock\(\)" || echo "  (Resolve not found)"
  echo "--- gate verdict on the artifact:"
  .venv/bin/python _deadlock_detector.py "$KEEP"/store.go 2>/dev/null
} > "${LOG}.summary"
cat "${LOG}.summary"
