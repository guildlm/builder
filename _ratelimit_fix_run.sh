#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")"
LOG="logs/ratelimit-fix-$(date +%m%d%H%M).log"
./_ab_run.sh ratelimit > "$LOG" 2>&1
KEEP="./generated/_ratelimit-AFTER"; rm -rf "$KEEP"; cp -r ./generated/ratelimit-v4 "$KEEP" 2>/dev/null
{
  echo "########## RATELIMIT FIX RESULT ##########"
  grep -hE "RESULT ratelimit|COVERAGE ratelimit|rejected .*candidate|re-locks" "$LOG" | tail -8
  echo "--- test funcs AFTER (want: BEFORE's 5 + TestBucketCapAfterIdle = 6, nothing lost):"
  grep -rhoE "^func Test[A-Za-z0-9_]+" "$KEEP" --include="*_test.go" | sort
  echo "--- BLAST RADIUS: names in BEFORE but not AFTER (want: none):"
  comm -23 /tmp/rl-before.txt <(grep -rhoE "^func Test[A-Za-z0-9_]+" "$KEEP" --include="*_test.go" | sort) || true
  echo "--- did the model write TestBucketCapAfterIdle?"
  grep -rq "func TestBucketCapAfterIdle" "$KEEP" && echo "YES" || echo "NO — dropped despite shown code"
} > "${LOG}.summary"
cat "${LOG}.summary"
