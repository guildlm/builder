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


def run_test(root: pathlib.Path, pkg: str, names: str) -> tuple[bool, str]:
    r = subprocess.run(["go", "test", pkg, "-run", f"^({names})$", "-count=1"],
                       cwd=root, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr)


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
    pkg = "./" + str(src.parent.relative_to(root)) if src.parent != root else "."

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

        ok, out = run_test(base, pkg, names)
        if not ok:
            return "PROBE-RED", (f"{names} FAILS on the unmutated tree — the test is wrong, "
                                 f"not the code:\n" + out.strip()[-400:])

        # Replace the Nth occurrence, leaving the others alone.
        head, sep, tail = "", "", text
        for _ in range(occurrence + 1):
            h, sep, tail = tail.partition(old)
            head += h + (sep if _ < occurrence else "")
        target.write_text(head + new + tail)
        ok, out = run_test(base, pkg, names)
        where = f"occurrence {occurrence} of {n_sites}"
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
