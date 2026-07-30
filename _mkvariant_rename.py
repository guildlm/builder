#!/usr/bin/env python3
"""Build an EQUAL-LENGTH single-identifier rename variant of a spec, or refuse.

    python _mkvariant_rename.py <src.yaml> <out.yaml> <OldName> <NewName>
    python _mkvariant_rename.py --self-test

WHY THIS EXISTS. Four name-swap arms have been drawn and every one of their variants was made
by an ad-hoc substitution, with the guard ("22410 bytes before == 22410 after; 1 substitution,
0 left behind") re-derived by hand each time and reported in prose. That is the same shape
_asdrawn_diff.py was written to kill: the collateral count the whole series turned on was being
read off by eye. A guard that is retyped per arm is a guard that is one typo from passing
vacuously, and this repo has already paid for that twice — the Delete-404 grader refused twice
on MY malformed regexes, and a guardless grader would have printed SURVIVED both times.

WHAT IT REFUSES, AND WHY EACH REFUSAL IS A DISTINCT BROKEN ARM RATHER THAN A NUISANCE

    unequal length      The series has a row for equal-length swaps and a separate row for
                        additions, because they behave differently: 4 name swaps perturbed 2,
                        6 non-rename edits perturbed 6. A rename that changes the byte count is
                        BOTH edits at once and lands in neither row.
    old occurs 0        The variant would be byte-identical to the source. The arm then measures
                        nothing, and — this is the failure that actually matters — it would look
                        exactly like the cleanest possible NULL. A null result and a null EDIT
                        are different claims; _asdrawn_diff.py makes the same distinction.
    old occurs >1       Not the single-variable manipulation the arm claims. Every causal claim
                        in this campaign rests on one changed thing.
    new occurs >0       The "new" name is already in the spec. That is the f0ba8f9 ambiguity as
                        a manipulation instead of a confound: collision and convention-breaking
                        stop being separable, which is the one thing that arm could not resolve.
    out exists          A silently overwritten variant is an arm graded against the wrong input,
                        and nothing downstream can detect it.

IDENTIFIER BOUNDARIES, WHICH A str.count() GUARD GETS WRONG. `TestBalance` occurs inside
`TestBalanceAfterTransaction`. A substring substitution would rewrite the longer identifier too
and the byte-count guard would still pass — equal-length in, equal-length out — so the arm would
carry an unnoticed second edit past every check. Counting and substituting both happen on
identifier boundaries. The unbounded count is reported alongside, because a name that ALSO
appears inside longer identifiers is a fact about the arm worth stating even when the bounded
substitution is the correct one.
"""
from __future__ import annotations

import pathlib
import re
import sys

IDENT = r"[A-Za-z0-9_]"


def _bounded(name: str) -> re.Pattern:
    return re.compile(rf"(?<!{IDENT}){re.escape(name)}(?!{IDENT})")


def plan(src: str, old: str, new: str) -> tuple[str, list[str]]:
    """Return (variant_text, notes) or raise ValueError naming the refusal."""
    if len(old) != len(new):
        raise ValueError(
            f"unequal length: {old!r} is {len(old)} chars, {new!r} is {len(new)}. "
            "That is a rename AND a size change — two edit kinds in one arm."
        )
    if old == new:
        raise ValueError("old and new are the same identifier: the variant would be the source.")

    n_old = len(_bounded(old).findall(src))
    n_old_sub = src.count(old)
    n_new = len(_bounded(new).findall(src))
    n_new_sub = src.count(new)

    if n_old == 0:
        extra = (
            f" It appears {n_old_sub}x only INSIDE longer identifiers — substituting would"
            " corrupt them." if n_old_sub else ""
        )
        raise ValueError(f"{old!r} does not occur as a whole identifier.{extra}")
    if n_old > 1:
        raise ValueError(f"{old!r} occurs {n_old}x — not a single-variable manipulation.")
    if n_new > 0:
        raise ValueError(f"{new!r} already occurs {n_new}x: renaming into it is a COLLISION.")

    out = _bounded(old).sub(new, src)

    # The guards restated as post-conditions. They are cheap, and a transformation that
    # satisfies its preconditions can still be wrong.
    if len(out) != len(src):
        raise ValueError(f"byte count moved {len(src)} -> {len(out)} on an equal-length rename.")
    if len(_bounded(old).findall(out)) != 0:
        raise ValueError(f"{old!r} survives in the variant.")
    if len(_bounded(new).findall(out)) != 1:
        raise ValueError(f"{new!r} occurs {len(_bounded(new).findall(out))}x in the variant, want 1.")
    if out == src:
        raise ValueError("variant is byte-identical to the source.")

    notes = [
        f"{len(src)} bytes before == {len(out)} after",
        "1 substitution, 0 left behind",
    ]
    if n_old_sub > n_old:
        notes.append(
            f"⚠️ {old!r} also appears {n_old_sub - n_old}x inside LONGER identifiers, left untouched"
        )
    if n_new_sub > n_new:
        notes.append(
            f"⚠️ {new!r} already appears {n_new_sub - n_new}x inside LONGER identifiers"
        )
    return out, notes


def _self_test() -> int:
    base = "a: TestBalanceMissingAccount here\nb: TestBalanceAfterTransaction\n"
    fails = []

    def want_ok(src, old, new, label):
        try:
            out, _ = plan(src, old, new)
        except ValueError as e:
            fails.append(f"{label}: refused unexpectedly ({e})")
            return None
        return out

    def want_refuse(src, old, new, label, needle):
        try:
            plan(src, old, new)
        except ValueError as e:
            if needle not in str(e):
                fails.append(f"{label}: refused for the wrong reason ({e})")
            return
        fails.append(f"{label}: ACCEPTED, should have refused")

    out = want_ok(base, "TestBalanceMissingAccount", "TestBalanceAccountMissing", "happy")
    if out is not None:
        if len(out) != len(base):
            fails.append("happy: byte count moved")
        if "TestBalanceAccountMissing" not in out:
            fails.append("happy: new name absent")
        if "TestBalanceAfterTransaction" not in out:
            fails.append("happy: an untargeted identifier was disturbed")

    want_refuse(base, "TestBalanceMissingAccount", "TestShort", "unequal", "unequal length")
    # Both 21 chars, so this reaches the occurrence guard instead of tripping the length one.
    # The first draft of this case did NOT, and the self-test caught it: it "passed" the absent
    # check by refusing for the length reason, which is exactly the vacuous-guard failure this
    # tool was written to prevent, reproduced inside its own test.
    want_refuse(base, "TestNotPresentAtAllXY", "TestAbsentFromTheSpec", "absent", "does not occur")
    want_refuse(base, "TestBalanceMissingAccount", "TestBalanceMissingAccount", "identity", "same identifier")

    # THE BOUNDARY CASE THIS TOOL EXISTS FOR: a prefix of a longer identifier. A str.count()
    # guard sees 2 and a substring substitution rewrites both, silently doubling the edit.
    pre = "x: TestBalance\ny: TestBalanceAfterTransaction\n"
    out = want_ok(pre, "TestBalance", "TestBalanc3", "boundary")
    if out is not None and "TestBalanceAfterTransaction" not in out:
        fails.append("boundary: rewrote the longer identifier too")

    # Whole-identifier occurrences twice -> not single-variable.
    want_refuse("p: TestFoo\nq: TestFoo\n", "TestFoo", "TestBar", "twice", "occurs 2x")
    # Renaming into a name that already exists.
    want_refuse("p: TestFoo\nq: TestBar\n", "TestFoo", "TestBar", "collision", "COLLISION")
    # Present ONLY inside a longer identifier -> refuse, and say so.
    want_refuse("z: TestBalanceXY\n", "TestBalance", "TestBalanc3", "inner", "INSIDE longer")

    if fails:
        print("SELF-TEST FAILED")
        for f in fails:
            print("  ✗", f)
        return 1
    # The count is the number of cases ENUMERATED after it. A banner whose number disagrees with
    # its own list is the miniature of what _selftest_all.sh was written about.
    print("self-test OK: 8 cases (happy, unequal, absent, identity, boundary, twice, collision, inner)")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--self-test"]:
        return _self_test()
    if len(argv) != 4:
        print(__doc__.strip().splitlines()[2].strip())
        return 2
    src_p, out_p, old, new = argv
    if pathlib.Path(out_p).exists():
        print(f"REFUSING: {out_p} already exists. Overwriting it would silently re-aim an arm.")
        return 3
    src = pathlib.Path(src_p).read_text()
    try:
        out, notes = plan(src, old, new)
    except ValueError as e:
        print(f"REFUSING: {e}")
        return 4
    pathlib.Path(out_p).write_text(out)
    print(f"wrote {out_p}: {old} -> {new} ({len(old)} -> {len(new)} chars)")
    for n in notes:
        print(f"  {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
