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

    _grade_scoped.py <artifact> <rel.go> <old-text> <new-text> <TestName>[,<TestName>...]
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


def grade(art: pathlib.Path, rel: str, old: str, new: str, names: str) -> tuple[str, str]:
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
        if old not in text:
            return "NOAPPLY", (f"{old!r} not present in {rel} — nothing was mutated, and a "
                               f"row about an unapplied mutation is not a measurement")

        ok, out = run_test(base, pkg, names)
        if not ok:
            return "PROBE-RED", (f"{names} FAILS on the unmutated tree — the test is wrong, "
                                 f"not the code:\n" + out.strip()[-400:])

        target.write_text(text.replace(old, new, 1))
        ok, out = run_test(base, pkg, names)
        if ok:
            return "SURVIVED", f"{names} still passes with {old!r} -> {new!r}: it does not defend this"
        return "CAUGHT", f"{names} fails on the mutant, as it should"


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
    if len(a) != 5:
        raise SystemExit(__doc__)
    art, rel, old, new, names = pathlib.Path(a[0]), a[1], a[2], a[3], a[4]
    v, note = grade(art, rel, old, new, names)
    print(f"{v:<11} {art.name}  {rel}  {old!r} -> {new!r}  via {names}")
    print(f"   {note}")
    print("   NARROWER THAN A SUITE GRADE, on purpose: this says the NAMED TEST catches the\n"
          "   mutation, not that the whole suite does. Use it when an unrelated failure has\n"
          "   the tree red, and say which one you used.")
