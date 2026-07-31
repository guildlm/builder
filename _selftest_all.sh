#!/usr/bin/env bash
# Run EVERY instrument's self-test, discovered rather than listed.
#
#   ./_selftest_all.sh          every tool
#   ./_selftest_all.sh --fast   skip the ones that shell out to `go` (safe beside a draw)
#
# WHY THIS EXISTS. _audit_all.sh opens with "Every MODEL-FREE audit, self-tests first" and
# closes with "all self-tests green; every finding above is a CANDIDATE, not a verdict." It
# self-tests NINE tools. Thirty-three have a --self-test. So that banner covered a quarter of
# the instruments and read as though it covered all of them — and every tool that produced
# today's findings was outside it: _twin_witness, _redraw_diff, _teeth_suite, _hole_hunt,
# _resweep_report, and the six written today.
#
# It is the same shape this repo keeps finding in its own gates: a green that is true of what
# it checked and false of what it implies. _resweep_report exits 2 on an unknown flag for this
# reason; _hole_hunt refuses to print OK when zero items were probed.
#
# DISCOVERED, NOT LISTED, and that is the actual fix. _audit_all.sh's list was correct when it
# was written and went stale silently as tools were added — nine names is what it had, and
# nobody notices a list that does not grow. Globbing for `--self-test` cannot go stale: a new
# instrument is covered the moment it is written, and one that LOSES its self-test shows up as
# a drop in the count rather than as silence.
set -uo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
FAST=0
[[ "${1:-}" == "--fast" ]] && FAST=1

FAILED=0
RAN=0
SKIPPED=0
declare -a FAILS=()

for t in _*.py; do
  grep -q -- '--self-test' "$t" || continue
  # SLOW = shells out to the Go toolchain. Those self-tests build and test real trees in
  # tempdirs, which is real CPU — and a mutation sweep competing with a generation for CPU is
  # the one contention this repo still has no guard for. --fast exists so this is runnable
  # beside a draw without becoming that contention.
  slow=0
  grep -qE '"go", *"(build|test|vet)"|\["go"|GO_TEST' "$t" && slow=1
  # ...and an explicit opt-in, because the regex above only sees tools that call go
  # DIRECTLY. A tool that reaches the toolchain through builder.GoToolchain is invisible
  # to it — measured 31 July: _repair_survival.py's self-test takes 3.7s of real Go while
  # --fast happily ran it beside a live draw, which is the one contention this flag exists
  # to prevent. Widening the regex was the wrong fix: _escalation_surface.py and
  # _gate_audit.py also name GoToolchain, and their self-tests take 0.5s and 0.9s because
  # they only use it in main(). Static text cannot tell which PATH the self-test takes, so
  # the tool declares it.
  grep -q '# selftest: slow' "$t" && slow=1
  if [[ $FAST -eq 1 && $slow -eq 1 ]]; then
    printf '  %-34s SKIPPED (--fast: shells out to go)\n' "$t"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi
  RAN=$((RAN + 1))
  if out=$($PY "$t" --self-test 2>&1); then
    printf '  %-34s %s\n' "$t" "$(echo "$out" | tail -1 | cut -c1-84)"
  else
    printf '  %-34s ** SELF-TEST FAILED **\n' "$t"
    echo "$out" | sed 's/^/        /' | tail -8
    FAILED=1
    FAILS+=("$t")
  fi
done

echo
echo "  ran $RAN · skipped $SKIPPED · failed ${#FAILS[@]}"
if [[ $FAILED -eq 1 ]]; then
  echo "  ** FAILING: ${FAILS[*]}"
  echo "  A tool whose self-test fails is not evidence. Fix it before citing its output."
  exit 1
fi
if [[ $SKIPPED -gt 0 ]]; then
  echo "  ⚠ $SKIPPED tool(s) were NOT run. This is not a full green — say so when citing it."
  exit 0
fi
echo "  every instrument with a self-test passed it."
