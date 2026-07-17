#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")"
SUM="logs/mutex-intra-$(date +%m%d%H%M).log"; : > "$SUM"
echo "########## shortener x3, GUILDLM_ENABLE_RULES=mutex_intra, ONE process ##########" >> "$SUM"
for i in 1 2 3; do
  echo "########## rep $i ##########" >> "$SUM"
  GUILDLM_ENABLE_RULES=mutex_intra ./_ab_run.sh shortener >> "$SUM" 2>&1
  KEEP="./generated/_shortener-INTRA-$i"; rm -rf "$KEEP"; cp -r ./generated/shortener-v4 "$KEEP" 2>/dev/null && echo "=== kept -> $KEEP ===" >> "$SUM"
  # the whole question: is Resolve still locking itself twice?
  DL=$(awk '/func \(s \*MemStore\) Resolve/,/^}/' "$KEEP"/store.go 2>/dev/null | grep -qE "RLock" && awk '/func \(s \*MemStore\) Resolve/,/^}/' "$KEEP"/store.go 2>/dev/null | grep -qE "[^R]Lock\(\)" && echo "RLock+Lock=DEADLOCK" || echo "single-lock=OK")
  echo "rep $i: Resolve=$DL" >> "$SUM"
done
echo "########## COMPLETE ##########" >> "$SUM"
grep -hE "^(rep [0-9]|RESULT|COVERAGE)" "$SUM" > "${SUM}.summary"; cat "${SUM}.summary" >> "$SUM"
echo "summary -> ${SUM}.summary"
