#!/usr/bin/env bash
set -uo pipefail; cd "$(dirname "$0")"
LOG="logs/lrucache-fix-$(date +%m%d%H%M).log"
./_ab_run.sh lrucache > "$LOG" 2>&1
KEEP="./generated/_lrucache-AFTER"; rm -rf "$KEEP"; cp -r ./generated/lrucache-v4 "$KEEP" 2>/dev/null
{
  echo "########## LRUCACHE FIX RESULT ##########"
  grep -hE "RESULT lrucache|COVERAGE lrucache|re-locks" "$LOG" | tail -4
  echo "--- test funcs AFTER:"; grep -rhoE "^func Test[A-Za-z0-9_]+" "$KEEP" --include="*_test.go" | sort
  echo "--- BLAST RADIUS (in BEFORE not AFTER):"; comm -23 /tmp/lru-before.txt <(grep -rhoE "^func Test[A-Za-z0-9_]+" "$KEEP" --include="*_test.go" | sort) || true
  echo "--- wrote TestUpdateMarksRecentlyUsed?"; grep -rq "func TestUpdateMarksRecentlyUsed" "$KEEP" && echo YES || echo NO
} > "${LOG}.summary"
cat "${LOG}.summary"
