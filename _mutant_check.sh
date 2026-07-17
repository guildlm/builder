#!/usr/bin/env bash
# Does the suite have TEETH? Break the code on purpose and see if anything bites.
#
# A test can be PRESENT and still prove nothing. _named_test_audit.py asks whether
# the spec's named test EXISTS; it matches on names, so a test that is written but
# vacuous — right name, missing assertion — passes the audit while the hole stays
# open. Names are checkable by grep. Teeth are not. Only a deliberate break is.
#
# The founding measurement, 2026-07-17: ledger's spec names SEVEN store tests and
# the model wrote SIX. The missing one was TestCreateTransactionMovesBalances, the
# only one that asserts the CREDIT side of a posting lands. With it absent, this
# mutant — every credit silently dropped, money vanishing from a double-entry
# ledger — passed build, vet and the ENTIRE suite. Coverage moved 63.6 -> 62.2,
# which is the added branch changing the statement count, not the metric noticing,
# and it is inside the band this project calls flat. Green is what would have
# shipped.
#
# So this is the check the green suite cannot perform on itself, made repeatable
# instead of something I did once by hand in a scratch directory.
#
# Usage: _mutant_check.sh <spec> [artifact-dir]
#   exit 0 = the suite CAUGHT the mutant (it has teeth)
#   exit 1 = the suite MISSED it (green on broken code — a real hole)
set -uo pipefail
cd "$(dirname "$0")"
SPEC="${1:?usage: _mutant_check.sh <spec> [artifact-dir]}"
ART="${2:-./generated/${SPEC}-v4}"
[ -d "$ART" ] || { echo "no artifact: $ART"; exit 2; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cp -r "$ART" "$WORK/proj"
cd "$WORK/proj"

# The mutants are per-spec and each one is a REAL bug a reader would call a bug,
# not a syntactic tweak: the point is to name a behaviour the project promises and
# then break exactly that promise.
case "$SPEC" in
  ledger)
    TARGET="internal/store/store.go"
    DESC="every credit silently dropped (double-entry ledger loses money)"
    python3 - "$TARGET" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text()
old = "\t\ts.balances[p.AccountID] += p.Amount"
new = ("\t\tif p.Amount > 0 { // MUTANT: drop every credit\n"
       "\t\t\ts.balances[p.AccountID] += p.Amount\n\t\t}")
if s.count(old) != 1:
    print(f"MUTANT DID NOT APPLY: found {s.count(old)} sites, need exactly 1.")
    print("The code moved. A mutant that does not apply is not a passing test —")
    print("it is no test at all. Fix the pattern before trusting this result.")
    sys.exit(3)
p.write_text(s.replace(old, new))
PY
    [ $? -eq 3 ] && exit 2
    ;;
  *)
    echo "no mutant defined for '$SPEC'."
    echo "Add one that breaks a promise the spec actually makes — and make it"
    echo "assert its own application, or a silently-unapplied mutant will report"
    echo "'caught' forever while measuring nothing."
    exit 2 ;;
esac

echo "### mutant: $DESC"
echo "### target: $TARGET"
# -count=1: this project has been burned by go's test cache once already (0fe717f),
# and a cached PASS from the unmutated tree is exactly the failure this check
# cannot afford — it would report teeth that are not there.
OUT="$(go build ./... 2>&1 && go vet ./... 2>&1 && go test -count=1 ./... 2>&1)"
RC=$?
echo "$OUT" | tail -8
echo
if [ $RC -eq 0 ]; then
  echo "MISSED — the suite is GREEN on broken code. The mutant survived."
  echo "Whatever test should have caught this is absent, or present and toothless."
  exit 1
else
  echo "CAUGHT — the suite went RED. It has teeth for this bug."
  echo "$OUT" | grep -E "^\s+--- FAIL|FAIL:|\.go:[0-9]+:" | head -4
  exit 0
fi
