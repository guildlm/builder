#!/usr/bin/env bash
# Redraw the whole corpus as -v5, so the week's spec repairs can be measured BEFORE/AFTER.
#
# This is the campaign's closing experiment and the only one that answers the question the
# closures cannot: twenty-nine sites were graded CAUGHT one at a time, on trees generated
# for that purpose. Does a corpus drawn fresh from the repaired specs actually hold FEWER
# holes than logs/hole-hunt-rows.tsv recorded — 170 rows, 111 CAUGHT, 48 candidates, 19 real?
#
# A per-closure grade answers "did this edit take". Only a redraw answers "is the corpus
# better", and they are not the same claim: draw 2 of taskflow won two clamps and silently
# lost a third one layer down, which no per-closure grade could have shown.
#
# RUN ORDER: this goes AFTER the closure queue and after the taskapipro config-wiring edit.
# Sweeping a half-repaired spec set produces an "after" number that is about neither state.
#
# NEVER OVERWRITE A LANDED DRAW. _ab_run_v5.sh opens with `rm -rf "$OUT"`, generated/ is
# gitignored, and this repo has already paid once for a glob that emptied 136 artifacts. So
# every target is checked FIRST and the whole sweep refuses if any exists — refusing costs a
# rename, and the other outcome is unrecoverable.
#
# --check runs every guard and stops before generating anything. It exists because the
# version without it tempted me into "just pipe it to head to see the guard fire", which
# is not an inspection — it is a launch whose output you stop reading. The script started
# for real and had to be killed. A script whose only mode is DO IT will eventually be run
# to find out what it would do.
set -uo pipefail
cd "$(dirname "$0")"
CHECK=0
[[ "${1:-}" == "--check" ]] && CHECK=1

SPECS=(shortener tasks-api taskflow ratelimit usersapi jsonapi kvservice logstats
       taskapi bitset walkv workerpool lrucache priorityqueue numkit genericset
       jsoncodec eventbus expreval demo-small taskapipro workapi)

existing=()
for s in "${SPECS[@]}"; do
  [[ -d "./generated/${s}-v5" ]] && existing+=("${s}-v5")
done
if (( ${#existing[@]} )); then
  echo "REFUSING: these -v5 trees already exist and this sweep would rm -rf them:"
  printf '  generated/%s\n' "${existing[@]}"
  echo
  echo "generated/ is gitignored, so a deleted artifact is gone. Rename them first, e.g."
  echo "  mv generated/workapi-v5 generated/workapi-v5-stale-\$(date +%m%d)"
  echo "(workapi-v5 dates from 26 Jul and is referenced by logs/gate-audit.txt, so it is"
  echo " evidence behind a published number, not scratch.)"
  exit 2
fi

# DO NOT WAIT ON A WORKER. REFUSE WHILE A SCHEDULER IS RUNNING.
#
# The first version of this script parked on `while pgrep -f "guildlm-build main"`, and I
# launched it while the closure queue still had three specs to go. That waiter is wrong for
# exactly the reason written down yesterday and then written again today: a queue spends
# real minutes BETWEEN its jobs running `go test -race -count=4`, and in that window no
# guildlm-build process exists while the corpus is very much still being written. This
# script would have woken in that gap and started a second generation beside the queue —
# two builds, one GPU, which is the failure that already cost this project a live build's
# files.
#
#   "no worker is running" and "the other scheduler finished" are not the same
#   proposition, and the gap between them is exactly one job boundary.
#
# That sentence was already in my save point. It did not stop me writing the same waiter a
# third time, because prose in a note is not a check in a script. So this refuses instead of
# waiting: a scheduler running means a human decision is due about ordering, and the whole
# point of refusing is that the decision gets made rather than raced.
SCHEDULERS=$(pgrep -fl '_run_queue.*\.sh|_sweep\.sh|_rebuild_corpus\.sh|_chain_run\.sh|_shortener_mirrors_run\.sh' | grep -v "$$" || true)
if [[ -n "$SCHEDULERS" ]]; then
  echo "REFUSING: another scheduler is running — sequence these by hand, do not race them:"
  echo "$SCHEDULERS" | sed 's/^/  /'
  echo
  echo "Wait for it to print its own completion line, then re-run this."
  exit 3
fi
if pgrep -f "guildlm-build main" > /dev/null; then
  echo "REFUSING: a generation is in flight. Two builds share one GPU exactly once."
  exit 3
fi

if (( CHECK )); then
  echo "--check: all guards pass. ${#SPECS[@]} specs would be drawn into generated/<spec>-v5."
  echo "Nothing generated. Re-run without --check to actually draw."
  exit 0
fi

export GUILDLM_SWEEP_LOG="logs/sweep-v5-$(date +%m%d%H%M).log"
echo "=== v5 corpus redraw starts $(date) -> $GUILDLM_SWEEP_LOG ==="
for s in "${SPECS[@]}"; do
  echo "########## SWEEP SPEC: $s ##########" >> "$GUILDLM_SWEEP_LOG"
  ./_ab_run_v5.sh "$s" >> "$GUILDLM_SWEEP_LOG" 2>&1
done
echo "=== v5 corpus redraw complete $(date) ==="
grep -E "^RESULT " "$GUILDLM_SWEEP_LOG" | sort

cat <<'NEXT'

NEXT — the measurement this redraw exists for:
  .venv/bin/python _hole_hunt.py --gen=v5      # writes logs/hole-hunt-rows-v5.tsv
  .venv/bin/python _redraw_diff.py logs/hole-hunt-rows.tsv logs/hole-hunt-rows-v5.tsv

_redraw_diff compares ORDINALLY — the same artifact/file/shape occurs many times and
collapsing the rows by text turned 149 into 82 the first time it was tried. Read the
CAUGHT->SURVIVED direction first: that is a closure that did not survive its own redraw,
and it is the only number that can retract a claim made this week.

TWO THINGS TO SAY OUT LOUD BEFORE READING THE RESULT, both measured, both limits:

1. THE COMPARABLE SET WILL BE SMALL, AND ITS SIZE IS THE HEADLINE, NOT A FOOTNOTE.
   Dry-run of the same comparison across the July 27 redraw: 99 comparable sites, and
   50 sites present only in the old sweep with 71 only in the new. Sites are keyed by
   (artifact, file, shape, ordinal), so a draw that moves a declaration to another file
   loses the key entirely — workapi has already done exactly that with Chain, putting it
   in router.go and leaving middleware.go a one-line package clause. A v4-vs-v5 diff has
   MORE of this, not less, because the specs deliberately changed. Report the comparable
   count first. A "0 regressions" over 12 comparable rows is not the same claim as over 99,
   and the difference is invisible unless the denominator is printed.

2. -v4 IS NOT A CLEAN PRE-CAMPAIGN BASELINE. Those trees were rebuilt on 27 July, after
   the corpus deletion, from the specs as they stood THAT MORNING — which already carried
   the ratelimit and jsonapi closures from the 26th. So the diff measures "the closures
   written after the rebuild", not "the whole campaign". The honest claim is bounded that
   way, and stating the bound is cheaper than having it found.
NEXT
