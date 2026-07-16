#!/usr/bin/env bash
# Snapshot each run's RAW generation — the 20 files as the model wrote them,
# before the fix loop rewrites any of them.
#
# Why this exists: I tried to bisect the divergence by diffing FINAL artifacts and
# concluded "files 1-13 were identical, so file 14's prompt was identical, so its
# output must be identical" — which contradicted the observed difference. The
# reasoning was wrong, not the observation: the fix loop edits files, so two runs
# that differed at GENERATION can be repaired into identical final artifacts while
# the knock-on effect on a later file's prompt survives. Final-artifact identity
# says nothing about generation-time identity, and every bisect built on it is
# invalid.
#
# So capture the real thing. The builder writes all 20 files, THEN starts fixing.
# Poll fast, keep the newest snapshot, and freeze it the moment the log says a fix
# round has begun — the last snapshot before that line is the raw generation.
#
# Touches nothing the experiment reads: it only copies out of the output dir.
set -uo pipefail
cd "$(dirname "$0")"
OUT="./generated/workapi-v4"
mkdir -p ./generated/_raw

seen_rep=0
while pgrep -f _iso_cachefix >/dev/null 2>&1; do
  LOG=$(ls -t logs/ab-workapi-v4-*.log 2>/dev/null | head -1)
  [[ -n "$LOG" ]] || { sleep 2; continue; }
  # One snapshot dir per builder log = per rep.
  REP=$(basename "$LOG" .log)
  if [[ -d "$OUT" ]]; then
    N=$(find "$OUT" -name "*.go" 2>/dev/null | wc -l | tr -d ' ')
    # Freeze once the fix loop starts: from here on the files are no longer the
    # model's own output.
    if grep -q "fix round 1/" "$LOG" 2>/dev/null; then
      if [[ ! -f "./generated/_raw/$REP.frozen" ]]; then
        touch "./generated/_raw/$REP.frozen"
        echo "$(date +%H:%M:%S) FROZEN $REP at $(find ./generated/_raw/$REP -name '*.go' 2>/dev/null | wc -l | tr -d ' ') go files"
      fi
    elif [[ "$N" -gt 0 ]]; then
      # DO NOT compare a snapshot that has no .frozen marker beside it. This swap
      # leaves a window where $REP does not exist, and a `cmp` landing in that
      # window reports a DIFF for a file that is byte-identical — I read exactly
      # that as "config.go diverges!" before checking, and `diff` then showed
      # nothing at all. The reader must wait for the marker; a mid-swap read is
      # the instrument talking about itself.
      rm -rf "./generated/_raw/$REP.tmp"
      cp -r "$OUT" "./generated/_raw/$REP.tmp" 2>/dev/null
      rm -rf "./generated/_raw/$REP"
      mv "./generated/_raw/$REP.tmp" "./generated/_raw/$REP" 2>/dev/null
      [[ "$REP" != "$seen_rep" ]] && { echo "$(date +%H:%M:%S) tracking $REP ($N go files)"; seen_rep="$REP"; }
    fi
  fi
  sleep 3
done
echo "watcher done"
