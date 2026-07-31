#!/usr/bin/env bash
# Does the freeze guard actually FIRE? A guard that has only ever been seen to stay quiet is not
# known to work.
#
# The first attempt at this test mutated src/builder.py BEFORE launching the runner, so the runner
# locked the mutated file and had nothing to detect — it refused for an unrelated reason and looked
# like a pass. The mutation has to land BETWEEN the lock and the check, which is a window of
# milliseconds inside a real run. So the guard is driven directly here, with the mutation in the
# middle.
#
# SOURCED, NOT RETYPED. The guard lives in _harness_lock.sh and this test sources that file, so it
# exercises the shipped functions rather than a copy that would pass forever after the real one
# drifted. It also checks that the RUNNERS use the shared guard instead of inlining their own —
# without that, the guard could be perfect and unused.
# selftest: fast
set -uo pipefail
cd "$(dirname "$0")"

source ./_harness_lock.sh

fails=0
say () { printf '  %-38s %s\n' "$1" "$2"; }

# ── the runners must actually use the shared guard, or this whole test is about nothing ──
for r in _parity_ab.sh _parity_xproc.sh; do
  [[ -e "$r" ]] || continue
  if grep -q '^source ./_harness_lock.sh' "$r" && grep -q 'harness_check' "$r"; then
    say "$r uses the shared guard" "yes  ✓"
  else
    say "$r uses the shared guard" "NO — it has drifted  ✗"; fails=1
  fi
done

SPEC=$(grep -m1 '^SPEC=' _parity_ab.sh | cut -d'"' -f2)
EXAMPLES=$(grep -m1 '^EXAMPLES=' _parity_ab.sh | cut -d'"' -f2)
[[ -e "$SPEC" && -e "$EXAMPLES" ]] || { echo "  FAIL: could not resolve SPEC/EXAMPLES from _parity_ab.sh"; exit 1; }

# ⚠️ THIS TEST MUTATES THE REAL src/builder.py, THE REAL SPEC AND THE REAL EXAMPLES FILE. It has
# to: a guard only ever shown a copy is not shown to guard anything. Every case restores its file
# on the next line — but a Ctrl-C or a kill BETWEEN the mutation and the restore would leave the
# project dirty, and the busiest of those files is the spec. So the restore is a trap, not a
# trailing line. Verified load-bearing: without the trap, a kill mid-test leaves builder.py +22
# bytes dirty. Same hazard class the guard itself exists for.
declare -a RESTORE=()
cleanup () { for pair in "${RESTORE[@]:-}"; do [[ -n "$pair" ]] && cp "${pair%%::*}" "${pair##*::}" 2>/dev/null; done; }
trap cleanup EXIT INT TERM
# ⚠️ TWO statements. `local f="$1" bak="…$f…"` reads f before it is assigned under bash 3.2 +
# set -u — the trap then registered nothing while the test still printed a full pass.
guard_file () {
  local f="$1"
  local bak="$TMPDIR/fg.$(echo "$f" | tr / _).$$"
  cp "$f" "$bak"; RESTORE+=("$bak::$f"); echo "$bak"
}

harness_lock_init "_parity_ab.sh" "$SPEC" "$EXAMPLES" >/dev/null

probe () {   # probe <file> <label>
  local bak; bak=$(guard_file "$1")
  printf '\n# freeze-guard probe\n' >> "$1"
  local out; out=$(harness_check 2>&1)
  if grep -q "the harness changed mid-run" <<<"$out"; then say "$2" "REFUSED  ✓"; else say "$2" "MISSED  ✗"; fails=1; fi
  cp "$bak" "$1"
}

out=$(harness_check 2>&1); [[ -z "$out" ]] && say "unchanged harness" "silent  ✓" || { say "unchanged harness" "SPOKE  ✗"; fails=1; }

probe src/builder.py "builder.py edited mid-run"
# "restored -> silent again" matters: a guard that LATCHES would refuse every draw after any
# touch, which is a different failure and would look like success in a test that only mutates.
out=$(harness_check 2>&1); [[ -z "$out" ]] && say "harness restored" "silent again  ✓" || { say "harness restored" "STILL REFUSING  ✗"; fails=1; }

probe "$SPEC"          "the SPEC edited mid-run"
probe "$EXAMPLES"      "the EXAMPLES file edited mid-run"
probe _parity_ab.sh    "the runner itself edited mid-run"
probe _harness_lock.sh "the guard's OWN file edited mid-run"

[[ $fails -eq 0 ]] && echo "  freeze guard: all checks passed" || echo "  freeze guard: FAILURES"
exit $fails
