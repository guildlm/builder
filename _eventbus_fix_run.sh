#!/usr/bin/env bash
set -uo pipefail; cd "$(dirname "$0")"
LOG="logs/eventbus-fix-$(date +%m%d%H%M).log"
./_ab_run.sh eventbus > "$LOG" 2>&1
KEEP="./generated/_eventbus-AFTER"; rm -rf "$KEEP"; cp -r ./generated/eventbus-v4 "$KEEP" 2>/dev/null
{
  echo "########## EVENTBUS FIX RESULT ##########"
  grep -hE "RESULT eventbus|COVERAGE eventbus|re-locks" "$LOG" | tail -4
  echo "--- funcs AFTER:"; grep -rhoE "^func Test[A-Za-z0-9_]+" "$KEEP" --include="*_test.go" | sort
  echo "--- BLAST RADIUS (before not after):"; comm -23 /tmp/eb-before.txt <(grep -rhoE "^func Test[A-Za-z0-9_]+" "$KEEP" --include="*_test.go" | sort) || true
  echo "--- wrote TestPublishNonBlockingWhenFull?"; grep -rq "func TestPublishNonBlockingWhenFull" "$KEEP" && echo YES || echo NO
} > "${LOG}.summary"
cat "${LOG}.summary"
