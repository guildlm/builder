#!/usr/bin/env python3
"""Run one draw's TESTS against another draw's CODE. Whose suite is stronger?

Two trees of the same spec are two independent attempts at the same contract. Their code
usually differs a little and their tests differ a lot, and a suite is only ever as strong
as the assertions that draw happened to write. So swap them:

    impl from A + tests from A   -> the baseline, should be green
    impl from A + tests from B   -> does B's suite see something A's does not?

The interesting cell is a tree that is GREEN ON ITS OWN SUITE and RED under a sibling's.
That is a defect its own tests never asked about, and no mutation shape can find it —
mutation testing breaks correct code and asks whether a test notices, which presumes the
code is correct. When the code is already wrong in every draw, there is nothing to break.

FOUND BY ACCIDENT, WHICH IS THE ARGUMENT FOR THE TOOL. tasks-api-v4 is green. Its
TestCreate201 asserts the created task's TITLE came back. A later draw wrote the same test
asserting the ID is non-zero, and it fails — on IDENTICAL code — because Create takes a
Task by value, assigns the id to its own copy, and the handler echoes the caller's. The
store gets id 1 and the client is told id 0. Green corpus, broken wire contract, six
mutation shapes and 170 probes blind to it.

    python _cross_draw.py taskflow            # every pair of taskflow trees
    python _cross_draw.py                     # every spec with two or more trees
    python _cross_draw.py --self-test

VERDICTS
  GREEN         the borrowed suite passes on this code
  RED           it fails, and the failing test names are printed — a defect this code's
                own suite does not check
  COMPILE-FAIL  the two draws disagree about the API (different constructor, different
                helper), so the suites are not interchangeable. Honest, not a finding.
  NO-BASELINE   the tree is not green on its OWN suite, so a cross verdict says nothing
"""
from __future__ import annotations

import collections
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

GEN = pathlib.Path("generated")
FAILED = re.compile(r"^\s*--- FAIL: (\w+)", re.M)
GO_TEST = ["go", "test", "-count=1", "-timeout", "120s", "./..."]


def draws() -> dict[str, list[pathlib.Path]]:
    """Trees grouped by the spec they came from: taskflow-v4 and taskflow-chain are one spec.

    Keyed by the artifact name with its trailing draw suffix removed. `tasks-api-v4` and
    `tasksapi-empty` are the same spec under different spellings, so the key drops
    non-alphanumerics too — otherwise the pair that motivated this tool would not group.
    """
    out = collections.defaultdict(list)
    for d in sorted(GEN.glob("*")):
        if not d.is_dir() or not any(d.rglob("*.go")):
            continue
        # SKIP PRESERVED DRAWS. _ab_run/_ab_run_v5 now move an existing tree to `<name>-prevN`
        # instead of deleting it, so generated/ accumulates superseded draws. This is the ONE
        # tool that globs generated/ broadly rather than keying on a -vN suffix.
        #
        # It was already harmless BY ACCIDENT: `taskapipro-v5-prev1` does not match the suffix
        # regex below, so it keys as its own spec, forms a singleton group, and is dropped by
        # the len(v) > 1 filter. That is a coincidence, not a decision — and it inverts badly.
        # If `prev` were ever added to that suffix list to "tidy up the grouping", preserved
        # trees would merge into the real spec group and get cross-tested against the draws
        # that superseded them, which is exactly the comparison nobody wants.
        # ANCHORED, and the first verification of it was wrong in the repo's favourite
        # way: `"prev" in name` reports True for `expreval-v4` — "ex-PREV-al" — so a
        # substring check "found" a preserved tree in a corpus that had none. Right
        # about its query, wrong about the world. Verified instead by planting a real
        # `-prev1` tree and confirming the group excludes it.
        if re.search(r"-prev\d+$", d.name):
            continue
        stem = re.sub(r"-(v\d+|chain\d*|witness|empty\d*|mirrors|ct|gated|min)$", "", d.name)
        out[re.sub(r"[^a-z0-9]", "", stem.lower())].append(d)
    return {k: v for k, v in out.items() if len(v) > 1}


def _run(work: pathlib.Path):
    return subprocess.run(GO_TEST, cwd=work, capture_output=True, text=True)


def cross(impl: pathlib.Path, tests: pathlib.Path) -> tuple[str, str]:
    """impl's code, tests' _test.go files."""
    with tempfile.TemporaryDirectory() as td:
        work = pathlib.Path(td) / "p"
        shutil.copytree(impl, work)
        for f in work.rglob("*_test.go"):
            f.unlink()
        n = 0
        for f in tests.rglob("*_test.go"):
            dest = work / f.relative_to(tests)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            n += 1
        if n == 0:
            return "NO-TESTS", f"{tests.name} has no _test.go to lend"
        r = _run(work)
    if r.returncode == 0:
        return "GREEN", f"{n} borrowed test file(s) pass"
    names = sorted(set(FAILED.findall(r.stdout + r.stderr)))
    if not names:
        return "COMPILE-FAIL", "the draws disagree about the API — suites not interchangeable"
    return "RED", "fails: " + ", ".join(names)


def report(groups) -> int:
    findings = both = 0
    for spec, trees in sorted(groups.items()):
        print(f"\n=== {spec} ({len(trees)} draws) ===")
        base, home_failures = {}, {}
        for t in trees:
            v, note = cross(t, t)
            base[t] = v
            home_failures[t] = set(re.findall(r"\w+", note.replace("fails:", ""))) \
                if v == "RED" else set()
            print(f"  baseline  {t.name:<24} {v:<13} {note}")
        for a in trees:
            for b in trees:
                if a is b:
                    continue
                if base[a] != "GREEN":
                    print(f"  {a.name} + {b.name} tests: NO-BASELINE "
                          f"({a.name} is not green on its own suite)")
                    continue
                v, note = cross(a, b)
                mark = ""
                if v == "RED":
                    failing = set(re.findall(r"\w+", note.replace("fails:", "")))
                    # A BORROWED TEST THAT ALSO FAILS AT HOME INDICTS BOTH DRAWS, and that
                    # is a different claim. Either the two implementations share a defect —
                    # tasks-api's Create-by-value, where the spec backs the test and both
                    # draws are wrong — or the test itself is broken, like taskflow's
                    # TestWireFieldNames requesting /tasks/1 and decoding an array. Only the
                    # SPEC separates those, so the label says which question to ask rather
                    # than pretending to answer it.
                    if failing & home_failures[b]:
                        mark = "  <-- BOTH-DRAWS: also fails at home; read the spec"
                        both += 1
                    else:
                        mark = "  <-- ASYMMETRIC: this code is weaker than its sibling"
                        findings += 1
                print(f"  impl {a.name:<22} + tests {b.name:<22} {v:<13} {note}{mark}")
    if not groups:
        raise SystemExit("no spec has two draws — nothing was compared, which is not a "
                         "clean report")
    # BOTH counts, because the first version made ASYMMETRIC the headline and it read
    # "0 findings" on a run that had just surfaced two real ones. Both of the genuine
    # cross-draw findings in this corpus are BOTH-DRAWS: tasks-api's Create-by-value, where
    # the spec backs the borrowed test and every draw is wrong, and taskflow's broken
    # TestWireFieldNames, where it does not. A headline that counts only the empty category
    # is the reassuring-wrong-answer shape this repo keeps finding in its own tools.
    print(f"\n{findings} ASYMMETRIC — code green on its own suite, red under a sibling's "
          "test that\n              passes where it was written. The sibling is stronger "
          "and this code is weaker.")
    print(f"{both} BOTH-DRAWS — the borrowed test fails at home too, so it indicts every "
          "draw at once.\n              Either they share a defect or the test is wrong, "
          "and only the SPEC says which.\n              Both of this corpus's real "
          "cross-draw findings landed here, one of each kind.")
    return 0


_MOD = "module example.com/x\n\ngo 1.23\n"
# The bug both draws share: Bump takes a value, so the caller never sees the increment.
_IMPL = ("package x\n\ntype Counter struct{ N int }\n\n"
         "func Bump(c Counter) Counter {\n\tc.N++\n\treturn c\n}\n\n"
         "func Apply(c Counter) Counter {\n\tBump(c)\n\treturn c\n}\n")
_WEAK = ('package x\n\nimport "testing"\n\nfunc TestApply(t *testing.T) {\n'
         '\tif Apply(Counter{N: 5}).N < 0 {\n\t\tt.Fatal("negative")\n\t}\n}\n')
_STRONG = ('package x\n\nimport "testing"\n\nfunc TestApply(t *testing.T) {\n'
           '\tif got := Apply(Counter{N: 5}).N; got != 6 {\n'
           '\t\tt.Fatalf("Apply = %d, want 6", got)\n\t}\n}\n')


def self_test() -> int:
    """The weak draw must be GREEN alone and RED under the strong draw's suite."""
    failures = []
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        weak, strong = root / "w", root / "s"
        for d, test in ((weak, _WEAK), (strong, _STRONG)):
            d.mkdir()
            (d / "go.mod").write_text(_MOD)
            (d / "x.go").write_text(_IMPL)
            (d / "x_test.go").write_text(test)
        if cross(weak, weak)[0] != "GREEN":
            failures.append("the weak draw must be green on its own suite")
        if cross(strong, strong)[0] != "RED":
            failures.append("the strong draw must be red on its own suite (same buggy code)")
        v, note = cross(weak, strong)
        if v != "RED":
            failures.append(f"weak code + strong tests must be RED, got {v} ({note})")
        v, _ = cross(strong, weak)
        if v != "GREEN":
            failures.append(f"strong code + weak tests must be GREEN, got {v}")
    # And an API disagreement must read COMPILE-FAIL rather than as a defect.
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        a, b = root / "a", root / "b"
        for d in (a, b):
            d.mkdir()
            (d / "go.mod").write_text(_MOD)
        (a / "x.go").write_text("package x\n\nfunc Alpha() int { return 1 }\n")
        (a / "x_test.go").write_text('package x\n\nimport "testing"\n\n'
                                     'func TestA(t *testing.T) { _ = Alpha() }\n')
        (b / "x.go").write_text("package x\n\nfunc Beta() int { return 1 }\n")
        (b / "x_test.go").write_text('package x\n\nimport "testing"\n\n'
                                     'func TestB(t *testing.T) { _ = Beta() }\n')
        v, _ = cross(a, b)
        if v != "COMPILE-FAIL":
            failures.append(f"draws with different APIs must be COMPILE-FAIL, got {v}")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("OK — a draw green on its own weak suite goes RED under a stronger sibling's,\n"
          "     the stronger suite is red on the shared bug, and an API disagreement reads\n"
          "     COMPILE-FAIL rather than as a defect")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    groups = draws()
    if wanted:
        keys = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in wanted]
        groups = {k: v for k, v in groups.items() if k in keys}
        if not groups:
            raise SystemExit("no spec with two draws matched " + " ".join(wanted) +
                             "\nknown: " + ", ".join(sorted(draws())))
    from _corpus_state import check as _corpus_check
    if any(_corpus_check(t) == "refuse" for ts in groups.values() for t in ts):
        raise SystemExit(2)
    raise SystemExit(report(groups))
