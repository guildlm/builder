#!/usr/bin/env bash
# Grade every boundary closure that has finished generating.
#
# Nine closures across seven artifacts, each graded with the SHAPE that found the hole and
# the FILE it lives in — the two things _hole_closed makes you state because getting either
# wrong reports a hole closed on a site nobody touched.
#
# Skips artifacts that are not there yet, so it can be run while the sweep is still going;
# _hole_closed itself refuses any tree that is being written. Grades nothing silently: an
# absent artifact is printed as absent, because "0 failures" over 0 graded artifacts reads
# exactly like success.
set -uo pipefail
cd "$(dirname "$0")"

grade() {  # <artifact> <spec> <probe> <file>
  local art="$1" spec="$2" probe="$3" file="$4"
  if [[ ! -d "$art" ]]; then
    echo "--- $art: NOT GENERATED YET (probe=$probe) ---"
    return
  fi
  echo
  echo "======== $art  probe=$probe  file=$file ========"
  .venv/bin/python _hole_closed.py "$art" "$spec" "--probe=$probe" "--file=$file"
}

grade generated/taskflow-chain   taskflow   chain-loop        middleware.go
grade generated/usersapi-chain   usersapi   chain-loop        middleware.go
grade generated/taskapi-chain    taskapi    chain-loop        internal/api/middleware.go
grade generated/taskapipro-chain taskapipro chain-loop        internal/api/middleware.go
grade generated/workapi-chain    workapi    chain-loop        internal/api/middleware.go

grade generated/workapi-chain    workapi    queue-size        internal/config/config.go
grade generated/taskapipro-chain taskapipro default-page-size internal/config/config.go

grade generated/bitset-witness   bitset     bitset-test       bitset.go
grade generated/bitset-witness   bitset     bitset-clear      bitset.go
