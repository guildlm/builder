#!/usr/bin/env python3
"""Grade ONE closure by ITS OWN test, when an unrelated failure has the tree red.

WHY. The verdict machinery asks "does the SUITE catch this mutation", and on a red tree the
answer is BASELINE-RED for every site — correct, and useless. Twice tonight a good closure
was unGRADEable for a reason that had nothing to do with it:

    taskapipro draw 3   internal/config failed a guard the impl entry never promised, while
                        internal/api — where the closure lives — was green.
    taskapi draw 2      TestHealthz compared a raw JSON body against `ok` and went red, while
                        the two empty-list closures it shares a package with were fine.

Scoping the run to the closure's OWN test answers the question the closure actually poses:
does the test I wrote catch the mutation I aimed it at? That is a NARROWER claim than the
suite-wide one and this tool prints it as narrower every time, because a scoped run that goes
unmentioned is how a weaker claim gets read as the stronger one.

WHAT IT CHECKS, in order — all three, or the verdict is not a verdict:
    1. the named test PASSES on the unmutated tree      (else PROBE-RED: the test is wrong)
    2. the named test FAILS on the mutated tree         (else SURVIVED: nothing here defends)
    3. the mutation actually APPLIED                    (else NOAPPLY: nothing was measured)

    _grade_scoped.py <artifact> <rel.go> <old-text> <new-text> <TestName>[,<TestName>] [occurrence]
    _grade_scoped.py --self-test
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile


def run_test(root: pathlib.Path, names: str) -> tuple[bool, bool, str]:
    """(passed, actually_ran, output) over the WHOLE module, filtered to `names`.

    NOT the mutated file's package. The first version scoped the run to the package holding
    the mutated line, and the defending test routinely lives somewhere else: taskapi's
    empty-list closure mutates internal/store/memory.go and is defended by a test in
    internal/api. `go test ./internal/store -run ^TestListEmptyIsEmptyArray$` reports
    "ok [no tests to run]" — a pass, from zero tests — and BOTH closures came back SURVIVED
    on the strength of it.

    So the run is module-wide with a -run filter, and "did anything actually run" is returned
    separately, because a gate that never fires is not a gate: a vacuous pass is exactly what
    a wrong package name produces, and it is indistinguishable from a real one by exit code.
    """
    r = subprocess.run(["go", "test", "./...", "-run", f"^({names})$", "-count=1", "-v"],
                       cwd=root, capture_output=True, text=True)
    out = r.stdout + r.stderr
    seen = {ln.split()[-1] for ln in out.splitlines() if ln.startswith("=== RUN")}
    # EVERY NAME MUST HAVE RUN, not just one of them. Reporting only "nothing ran" leaves
    # the far likelier mistake invisible: a filter of three names where one is misspelled
    # silently narrows to two, and the site that only the missing test defends comes back
    # SURVIVED. That happened — grading shortener's 400 mirrors I passed
    # TestShortenEmptyURL, the actual test is TestShortenBadRequest, and the empty-url site
    # reported SURVIVED. I was one sentence from recording a regression that did not exist.
    missing = [n for n in names.split("|") if n and n not in seen]
    return r.returncode == 0, (bool(seen), missing), out


def grade(art: pathlib.Path, rel: str, old: str, new: str, names: str,
          occurrence: int = 0) -> tuple[str, str]:
    """`occurrence` selects WHICH site — text is not an address.

    Found by running this tool on a real tree instead of only on fixtures. Asked to grade
    taskapipro's projects.go clamp, the first version replaced the FIRST `offset = 0` in the
    file — the strconv error fallback — and reported SURVIVED, while a per-line grade of the
    same tree had the clamp CAUGHT. Both were right: the closure's test sends
    `?limit=10&offset=-1`, so offset parses, the error branch never runs, and mutating it
    cannot change what that test sees. The site the closure defends is the SECOND occurrence.

    Every other instrument in this repo learned this and has a replace_at; this one shipped
    without it and produced a confident wrong verdict on its first real input. A single
    textual match is an address only in a file where the text appears once."""
    mod = next((p for p in art.rglob("go.mod")), None)
    if mod is None:
        return "SKIP", "no go.mod"
    root = mod.parent
    src = root / rel
    if not src.exists():
        src = art / rel
        if not src.exists():
            return "SKIP", f"{rel} not found"
    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td) / "t"
        shutil.copytree(root, base)
        target = base / src.relative_to(root)
        text = target.read_text()
        n_sites = text.count(old)
        if n_sites <= occurrence:
            return "NOAPPLY", (f"{old!r} occurs {n_sites}x in {rel}; occurrence {occurrence} "
                               f"does not exist — nothing was mutated, and a row about an "
                               f"unapplied mutation is not a measurement")

        ok, (ran, missing), out = run_test(base, names)
        if not ran:
            return "NOTESTS", (f"{names} matched NO test in this module — nothing ran, and a "
                               f"pass from zero tests is not evidence. Check the name.")
        if missing:
            return "NOTESTS", (f"these names matched NO test and were silently dropped from "
                               f"the filter: {', '.join(missing)}. The verdict would be about "
                               f"a NARROWER set of tests than you asked for, which is how a "
                               f"defended site reports SURVIVED.")
        if not ok:
            # DO NOT ATTRIBUTE THE CAUSE. This used to read "the test is wrong, not the
            # code", which is the right default for a probe I wrote against a tree believed
            # good — and it was exactly backwards the first time it fired on real data.
            # taskapi-v5 shipped `var tasks []models.Task`, so an empty list marshals as
            # `null`, and TestListEmptyIsEmptyArray failed on the unmutated tree because the
            # CODE has the defect the test was written to defend against. The tool announced
            # the opposite with confidence.
            #
            # It cannot tell these apart — that needs knowing whether the artifact is
            # correct, which is the whole question. So it reports the fact and names both
            # readings instead of choosing one.
            return "PROBE-RED", (
                f"{names} FAILS on the UNMUTATED tree. TWO readings, and this tool cannot\n"
                f"   choose between them: either the test is wrong, OR the artifact already "
                f"has\n   the defect the test defends against — in which case the test is "
                f"working and\n   the closure is doing its job. Read the failure before "
                f"concluding.\n" + out.strip()[-400:])

        # Replace the Nth occurrence, leaving the others alone.
        head, sep, tail = "", "", text
        for _ in range(occurrence + 1):
            h, sep, tail = tail.partition(old)
            head += h + (sep if _ < occurrence else "")
        target.write_text(head + new + tail)
        ok, _, out = run_test(base, names)
        where = f"occurrence {occurrence} of {n_sites}"
        # A MUTANT THAT DOES NOT COMPILE IS NOT A CAUGHT MUTANT. `go test` exits non-zero
        # for a build error exactly as it does for a failing assertion, and this tool read
        # both as "the test noticed". Caught on its second real input: replacing the RHS of
        # `out := make([]T, 0, n)` with `var out []T` yields `out := var out []T`, which is
        # not Go — and it was reported CAUGHT, which would have let me record a closure as
        # holding on the strength of a syntax error.
        if not ok and ("[build failed]" in out or "syntax error" in out
                       or "cannot use" in out or "undefined:" in out
                       or "declared and not used" in out or "expected " in out):
            return "BROKEN-MUTANT", (
                f"the mutant does not COMPILE, so nothing was tested — this is a defect in "
                f"the mutation, not a verdict about the site:\n" + out.strip()[-400:])
        if ok:
            return "SURVIVED", (f"{names} still passes with {old!r} -> {new!r} at {where}: "
                                f"it does not defend THAT site"
                                + (f". {n_sites} sites match this text — check you aimed at "
                                   f"the right one." if n_sites > 1 else ""))
        return "CAUGHT", f"{names} fails on the mutant at {where}, as it should"


def self_test() -> int:
    fails = []
    def build(td, impl, tests):
        art = pathlib.Path(td)
        (art / "go.mod").write_text("module example.com/t\n\ngo 1.23\n")
        (art / "t.go").write_text(impl)
        (art / "t_test.go").write_text(tests)
        return art

    GOOD = "package t\n\nfunc Limit(n int) int {\n\tif n < 0 {\n\t\treturn 0\n\t}\n\treturn n\n}\n"
    # TestMine defends the clamp; TestUnrelated is RED on purpose and must not matter.
    TESTS = ('package t\n\nimport "testing"\n\n'
             'func TestMine(t *testing.T) { if Limit(-1) != 0 { t.Fatal("want 0") } }\n'
             'func TestUnrelated(t *testing.T) { t.Fatal("red for an unrelated reason") }\n')
    with tempfile.TemporaryDirectory() as td:
        art = build(td, GOOD, TESTS)
        v, note = grade(art, "t.go", "return 0", "return 7777", "TestMine")
        if v != "CAUGHT":
            fails.append(f"the closure's own test must be gradeable THROUGH an unrelated red "
                         f"test — that is the entire point: {v} {note}")
    with tempfile.TemporaryDirectory() as td:
        art = build(td, GOOD, TESTS)
        v, _ = grade(art, "t.go", "return n", "return n", "TestMine")
        if v != "SURVIVED":
            fails.append(f"a no-op mutation the test cannot see is SURVIVED: {v}")
    with tempfile.TemporaryDirectory() as td:
        art = build(td, GOOD, TESTS)
        v, _ = grade(art, "t.go", "return 0", "return 7777", "TestUnrelated")
        if v != "PROBE-RED":
            fails.append(f"a test that fails on the CLEAN tree is PROBE-RED, never a verdict "
                         f"about the site: {v}")
    with tempfile.TemporaryDirectory() as td:
        art = build(td, GOOD, TESTS)
        v, _ = grade(art, "t.go", "nothing like this", "x", "TestMine")
        if v != "NOAPPLY":
            fails.append(f"an unapplied mutation must say so, not report a verdict: {v}")

    # THE BUG THIS TOOL SHIPPED WITH: two sites, same text, and only the second is defended.
    TWO = ("package t\n\nfunc A(n int) int {\n\tif n > 9 {\n\t\treturn 0\n\t}\n\treturn n\n}\n"
           "func B(n int) int {\n\tif n < 0 {\n\t\treturn 0\n\t}\n\treturn n\n}\n")
    T2 = ('package t\n\nimport "testing"\n\n'
          'func TestB(t *testing.T) { if B(-1) != 0 { t.Fatal("want 0") } }\n')
    with tempfile.TemporaryDirectory() as td:
        art = build(td, TWO, T2)
        v, _ = grade(art, "t.go", "return 0", "return 7777", "TestB", 0)
        if v != "SURVIVED":
            fails.append(f"occurrence 0 is A's clamp, which TestB does not defend: {v}")
        v, _ = grade(art, "t.go", "return 0", "return 7777", "TestB", 1)
        if v != "CAUGHT":
            fails.append(f"occurrence 1 is B's clamp, which TestB DOES defend — text is not "
                         f"an address, and this is the verdict the first version got wrong: {v}")
        v, _ = grade(art, "t.go", "return 0", "return 7777", "TestB", 9)
        if v != "NOAPPLY":
            fails.append(f"an occurrence that does not exist is NOAPPLY: {v}")

    # A MUTANT THAT DOES NOT COMPILE must never read as CAUGHT.
    with tempfile.TemporaryDirectory() as td:
        art = build(td, GOOD, TESTS)
        v, _ = grade(art, "t.go", "return 0", "return =% 0", "TestMine")
        if v != "BROKEN-MUTANT":
            fails.append(f"a mutant that does not compile is a broken mutation, not a caught "
                         f"one — go test exits non-zero for both: {v}")

    # A NAME THAT MATCHES NOTHING must not read as a pass. This is how both taskapi
    # closures came back SURVIVED: the run was scoped to the mutated file's package, the
    # defending test lived in another one, `go test` said "ok [no tests to run]", and a
    # vacuous pass is indistinguishable from a real one by exit code.
    with tempfile.TemporaryDirectory() as td:
        art = build(td, GOOD, TESTS)
        v, _ = grade(art, "t.go", "return 0", "return 7777", "TestNoSuchName")
        if v != "NOTESTS":
            fails.append(f"a test name matching nothing must be NOTESTS, never a verdict: {v}")

    # A MISSPELLED NAME AMONG GOOD ONES must not silently narrow the filter.
    with tempfile.TemporaryDirectory() as td:
        art = build(td, GOOD, TESTS)
        v, note = grade(art, "t.go", "return 0", "return 7777", "TestMine|TestTypoed")
        if v != "NOTESTS":
            fails.append(f"a name matching nothing, alongside one that does, must be "
                         f"reported — otherwise a defended site reads SURVIVED: {v}")

    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — grades through an unrelated red test, and refuses when the "
                           "probe itself is red or unapplied"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    a = [x for x in sys.argv[1:] if not x.startswith("-")]
    if len(a) not in (5, 6):
        raise SystemExit(__doc__)
    art, rel, old, new, names = pathlib.Path(a[0]), a[1], a[2], a[3], a[4]
    occ = int(a[5]) if len(a) == 6 else 0
    v, note = grade(art, rel, old, new, names, occ)
    print(f"{v:<11} {art.name}  {rel}  {old!r} -> {new!r}  via {names}")
    print(f"   {note}")
    print("   NARROWER THAN A SUITE GRADE, on purpose: this says the NAMED TEST catches the\n"
          "   mutation, not that the whole suite does. Use it when an unrelated failure has\n"
          "   the tree red, and say which one you used.")
