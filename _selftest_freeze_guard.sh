#!/usr/bin/env bash
# Does _parity_ab.sh's freeze guard actually FIRE? A guard that has only ever been seen to
# stay quiet is not known to work.
#
# The first attempt at this test mutated src/builder.py BEFORE launching the runner, so the
# runner locked the mutated file and had nothing to detect — it refused for an unrelated
# reason and looked like a pass. The mutation has to land BETWEEN the lock and the check,
# which is a window of milliseconds inside a real run. So the guard's own lines are lifted
# out of the runner by marker and exercised here with the mutation in the middle.
#
# EXTRACTED, NOT RETYPED. A hand-copied guard would test this file's copy and pass forever
# after the runner's version drifted. awk pulls the shipped text; if the markers move the
# test fails loudly rather than silently checking nothing.
# selftest: fast
set -uo pipefail
cd "$(dirname "$0")"

# SPEC and EXAMPLES are lifted from the runner too, so this test can never guard a different
# file than the runner draws with — the one way a passing guard test could still be a lie.
eval "$(grep -E '^(SPEC|EXAMPLES)=' _parity_ab.sh)"
lock_src=$(awk '/^HARNESS_FILES=/,/^WANT_HARNESS=/' _parity_ab.sh)
chk_src=$(awk '/^  local now; now=/,/    return 6; }/' _parity_ab.sh)
[[ -n "$lock_src" && -n "$chk_src" ]] || { echo "FAIL: could not extract the guard from _parity_ab.sh"; exit 1; }
grep -q 'shasum' <<<"$lock_src" || { echo "FAIL: extracted lock has no shasum"; exit 1; }
grep -q 'return 6' <<<"$chk_src" || { echo "FAIL: extracted check has no refusal"; exit 1; }

eval "${lock_src//\"\$0\"/\"_parity_ab.sh\"}"
check () { eval "$chk_src"; return 0; }

# ⚠️ THIS TEST MUTATES THE REAL src/builder.py, THE REAL SPEC AND THE REAL EXAMPLES FILE. It
# has to: a guard that is only ever shown a copy is not shown to guard anything. Every case
# restores its file on the next line — but a Ctrl-C or a kill BETWEEN the mutation and the
# restore would leave the project dirty, and the busiest of those files is the spec. So the
# restore is a trap, not a trailing line. Same hazard class the guard itself exists for.
declare -a RESTORE=()
cleanup () { for pair in "${RESTORE[@]:-}"; do [[ -n "$pair" ]] && cp "${pair%%::*}" "${pair##*::}" 2>/dev/null; done; }
trap cleanup EXIT INT TERM
# ⚠️ TWO statements. `local f="$1" bak="…$f…"` reads f before it is assigned under bash 3.2 +
# set -u — the trap then registered nothing while the test still printed 6/6.
guard_file () {
  local f="$1"
  local bak="$TMPDIR/fg.$(echo "$f" | tr / _).$$"
  cp "$f" "$bak"; RESTORE+=("$bak::$f"); echo "$bak"
}

fails=0
say () { printf '  %-38s %s\n' "$1" "$2"; }

out=$(check 2>&1); [[ -z "$out" ]] && say "unchanged harness" "silent  ✓" || { say "unchanged harness" "SPOKE: $out  ✗"; fails=1; }

bak=$(guard_file src/builder.py)
printf '\n# freeze-guard probe\n' >> src/builder.py
out=$(check 2>&1)
if grep -q "the harness changed mid-run" <<<"$out"; then say "builder.py edited mid-run" "REFUSED  ✓"; else say "builder.py edited mid-run" "MISSED  ✗"; fails=1; fi
cp "$bak" src/builder.py

out=$(check 2>&1); [[ -z "$out" ]] && say "harness restored" "silent again  ✓" || { say "harness restored" "STILL REFUSING  ✗"; fails=1; }

# the runner itself is the second guarded file, and it is the one a HEAD check would also miss
# the spec: 191 edits on record, the busiest file in the campaign and the whole point of the widening
bak=$(guard_file "$SPEC")
printf '\n# freeze-guard probe\n' >> "$SPEC"
out=$(check 2>&1)
if grep -q "the harness changed mid-run" <<<"$out"; then say "the SPEC edited mid-run" "REFUSED  ✓"; else say "the SPEC edited mid-run" "MISSED  ✗"; fails=1; fi
cp "$bak" "$SPEC"

bak=$(guard_file "$EXAMPLES")
printf '\n' >> "$EXAMPLES"
out=$(check 2>&1)
if grep -q "the harness changed mid-run" <<<"$out"; then say "the EXAMPLES file edited mid-run" "REFUSED  ✓"; else say "the EXAMPLES file edited mid-run" "MISSED  ✗"; fails=1; fi
cp "$bak" "$EXAMPLES"

bak=$(guard_file _parity_ab.sh)
printf '\n# freeze-guard probe\n' >> _parity_ab.sh
out=$(check 2>&1)
if grep -q "the harness changed mid-run" <<<"$out"; then say "the runner itself edited mid-run" "REFUSED  ✓"; else say "the runner itself edited mid-run" "MISSED  ✗"; fails=1; fi
cp "$bak" _parity_ab.sh

[[ $fails -eq 0 ]] && echo "  freeze guard: 6/6" || echo "  freeze guard: FAILURES"
exit $fails
