#!/usr/bin/env python3
"""Which tests exist in the artifact but are NAMED NOWHERE in the spec?

Those are the ones an edit can silently delete. Measured, not theorised: adding ONE named
test to jsonapi's entry cost THREE unnamed ones — TestValidMessage, TestEmptyMessage and
TestNonPOSTMethod, described in prose and never named — and the 405 defence went with them,
flipping a registered mutation from CAUGHT to SURVIVED. The named list becomes the file's
inventory, and everything unnamed beside it is at risk the moment anything in that entry is
named.

So the rule is not "add names carefully". It is: before naming anything in an entry, name
everything already in it. This says where that debt sits.

    python _unnamed_tests.py [spec ...]     # default: every spec with a -v4 artifact
    python _unnamed_tests.py --self-test

WHAT IT CANNOT SEE
  A test the model has ALREADY dropped. This compares the spec against the tree as it
  stands, so a promise that was never written leaves no trace here — that is what
  _hole_hunt and _named_test_audit are for. This answers the opposite question: what is
  present, load-bearing, and unprotected by a name.
"""
from __future__ import annotations

import pathlib
import re
import sys

NAME_RE = re.compile(r"\b(Test[A-Z]\w*)")
FUNC_RE = re.compile(r"^func (Test\w+)", re.M)


def spec_named(spec_text: str) -> set[str]:
    return set(NAME_RE.findall(spec_text))


def tree_tests(tree: pathlib.Path) -> set[str]:
    out: set[str] = set()
    for f in tree.rglob("*_test.go"):
        out |= set(FUNC_RE.findall(f.read_text(errors="ignore")))
    return out


def unnamed(spec_text: str, tree: pathlib.Path) -> list[str]:
    return sorted(tree_tests(tree) - spec_named(spec_text))


def self_test() -> int:
    import tempfile
    fails = []
    with tempfile.TemporaryDirectory() as td:
        tree = pathlib.Path(td) / "x-v4"
        tree.mkdir()
        (tree / "a_test.go").write_text(
            "package main\n\nfunc TestNamed(t *testing.T) {}\n"
            "func TestUnnamed(t *testing.T) {}\n")
        spec = "purpose: TestNamed: does a thing.\n"
        got = unnamed(spec, tree)
        if got != ["TestUnnamed"]:
            fails.append(f"expected the unnamed test to be reported alone, got {got}")
        # A spec that names a test the tree does NOT have is a different question and must
        # not appear here — reporting it would mix "at risk" with "already missing".
        if unnamed("purpose: TestNamed, TestGone.\n", tree) != ["TestUnnamed"]:
            fails.append("a spec-named test missing from the tree must not be reported")
        # Subtests and helpers are not test functions; only `func TestX` counts.
        (tree / "b_test.go").write_text(
            'package main\n\nfunc helperTestThing() {}\n'
            'func TestOther(t *testing.T) { t.Run("TestInner", func(t *testing.T) {}) }\n')
        got = unnamed(spec, tree)
        if "TestInner" in got or "helperTestThing" in got:
            fails.append(f"a subtest name or helper leaked into the report: {got}")
        if "TestOther" not in got:
            fails.append("a second file's unnamed test was missed")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — reports present-but-unnamed only, ignores subtests and "
                           "spec-only names"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    root = pathlib.Path(__file__).resolve().parent
    targets = [pathlib.Path(a) for a in sys.argv[1:] if not a.startswith("-")]
    if not targets:
        targets = sorted((root / "specs").glob("*.yaml"))
    for t in targets:
        if not t.is_file():
            raise SystemExit(f"{t} is not a file")
    checked = flagged = total = 0
    print(f"{'spec':<14} {'named':>6} {'in tree':>8}   tests present but NAMED NOWHERE")
    for spec in targets:
        tree = root / "generated" / f"{spec.stem}-v4"
        if not tree.is_dir():
            continue
        checked += 1
        text = spec.read_text()
        extras = unnamed(text, tree)
        if not extras:
            continue
        flagged += 1
        total += len(extras)
        print(f"{spec.stem:<14} {len(spec_named(text)):>6} {len(tree_tests(tree)):>8}   "
              f"{', '.join(extras)}")
    # DENOMINATOR: how many specs had an artifact to compare against at all. "0 flagged"
    # out of 0 compared is not a clean corpus, it is an unasked question — the failure this
    # repo's instruments keep being caught in.
    print(f"\n{total} unnamed test(s) across {flagged} spec(s); {checked} spec(s) had a "
          f"-v4 artifact to compare against")
    if not checked:
        print("no artifact matched — nothing was compared, which is not a pass")
