#!/usr/bin/env bash
# Every MODEL-FREE audit, self-tests first, in one command.
#
# WHY THIS EXISTS, and it is not tidiness. Tonight I found taskapi's TestMalformedJSON named
# in its spec since 2026-07-11 and absent from two draws, decided a tool was needed to catch
# "the spec names it, nobody wrote it", designed one, and was partway through writing it when
# I opened _named_test_audit.py and found that exact tool, with a better docstring than mine,
# built weeks ago for the same reason.
#
# There are 25 instruments in this directory. Nothing lists them, nothing runs them together,
# and the cost of that is not a wasted hour — it is that an audit nobody runs reports nothing,
# which is indistinguishable from an audit that found nothing.
#
# Everything here is source-only: no model, no GPU, no generation. Seconds, not hours.
# The mutation sweep, the closure grades and the reachability coverage runs are NOT here —
# they run `go test` per site and belong to _hole_hunt / _grade_*.sh / _reachability.
#
# SELF-TEST FIRST, ALWAYS. Every tool here has planted fixtures and a reject-nothing pin, and
# a green audit from a broken instrument is the worst output this project can produce — three
# separate times a tool's completeness check had been quietly calibrated to the bug it was
# built to catch. If a self-test fails, its findings below are not evidence.
set -uo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
FAILED=0

section() { echo; echo "════════════════════════════════════════════════════════════"; echo "  $1"; echo "════════════════════════════════════════════════════════════"; }

selftest() {  # <script> — a failed self-test disqualifies that tool's findings, not the run
  local t="$1"
  if out=$($PY "$t" --self-test 2>&1); then
    printf '  %-26s %s\n' "$t" "$(echo "$out" | tail -1)"
  else
    printf '  %-26s ** SELF-TEST FAILED — ignore its findings below **\n' "$t"
    echo "$out" | sed 's/^/      /'
    FAILED=1
  fi
}

section "SELF-TESTS"
# DISCOVERED, NOT LISTED. This section used to name NINE tools while thirty-three carried a
# --self-test, and it closed with "all self-tests green" — a banner true of what it checked
# and false of what it implied. Every instrument behind 29 July's findings was outside it.
# A hardcoded list was correct when written and went stale in silence, because nobody notices
# a list that stops growing. _selftest_all.sh globs for the flag instead, so a new tool is
# covered the moment it exists and a tool that LOSES its self-test shows as a falling count.
if [[ -x ./_selftest_all.sh ]]; then
  ./_selftest_all.sh || FAILED=1
else
  echo "  _selftest_all.sh missing — falling back to the historical nine, which is NOT full"
  for t in _spec_count_audit.py _promise_gap.py _dead_config.py _route_coverage.py \
           _named_test_audit.py _unnamed_tests.py _named_present.py \
           _mirror_calls_audit.py _registry_drift.py; do
    [[ -f "$t" ]] && selftest "$t"
  done
fi

section "SPEC-INTERNAL — does the spec contradict or shortchange itself?"
echo "-- stated test count vs enumerated tests, and entries that state two counts"
$PY _spec_count_audit.py 2>&1 | tail -20
echo
echo "-- a guard demanded by a TEST entry that no implementation entry promises"
$PY _promise_gap.py 2>&1 | tail -14

section "SPEC vs TREE — was what the spec asked for actually built?"
echo "-- tests the spec NAMES that no test file contains"
echo "   NOTE: this skips any artifact missing a spec-declared file, because a run in"
echo "   flight looks identical to a model refusing to write. Every -v4 tree now lacks"
echo "   middleware_chain_test.go (the Chain closure postdates them), so the HTTP specs"
echo "   are skipped. Date the missing names against the artifact before believing a gap:"
echo "   of 41 absences measured tonight, 29 were only the spec being newer than the tree."
$PY _named_test_audit.py 2>&1 | tail -18
echo
echo "-- PER DRAW: tests the spec names that this draw did not write"
echo "   A missing name is STOCHASTIC, not a dead spec sentence — two names measured on"
echo "   2026-07-28 were absent from some draws and present in others. The remedy is this"
echo "   check per draw, NOT rewriting the sentence. Rows whose spec is newer than the tree"
echo "   are labelled: a name added after a draw cannot be in it."
$PY _named_present.py 2>/dev/null | tail -14
echo
echo "-- tests present in a tree that the spec names NOWHERE (a later edit deletes these)"
$PY _unnamed_tests.py 2>&1 | tail -6

section "TREE-INTERNAL — promises with nothing behind them"
echo "-- config fields parsed, validated, tested, and read by NOBODY"
$PY _dead_config.py 2>&1 | tail -12
echo
echo "-- registered routes no test ever REQUESTS"
$PY _route_coverage.py 2>&1 | tail -12
echo
echo "-- structural twins that do not make the same calls"
[[ -f _mirror_calls_audit.py ]] && $PY _mirror_calls_audit.py 2>&1 | tail -8

section "SUMMARY"
if (( FAILED )); then
  echo "  ** at least one self-test FAILED — the findings above are not evidence **"
else
  echo "  self-tests green (see the SELF-TESTS section for how many RAN — a --fast run"
  echo "  skips the go-shelling tools and says so). Every finding above is a CANDIDATE,"
  echo "  not a verdict."
fi
echo "  Not run here (they cost go-test time, minutes to hours):"
echo "    _hole_hunt.py --all-sites     mutation sweep        -> logs/hole-hunt-rows.tsv"
echo "    _reachability.py              coverage per artifact -> logs/reachability-rows.tsv"
echo "    _bound_probe.py               is a survivor observable at all"
echo "    _grade_0728.sh / _grade_closures.sh   per-site closure grades"
exit $FAILED
