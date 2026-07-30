#!/usr/bin/env python3
"""Build a TRANSPOSITION variant of a spec — same characters, reordered — or refuse.

    python _mkvariant_swap.py <src.yaml> <out.yaml> "<old phrase>" "<new phrase>"
    python _mkvariant_swap.py --self-test

WHY A SECOND TOOL AND NOT A FLAG ON _mkvariant_rename.py. That tool answers "rename ONE
identifier, on identifier boundaries, equal length". This answers "reorder words inside a phrase",
which needs a different guard: the strongest possible check here is that the two strings are
ANAGRAMS — the same character multiset — because then equal length is a consequence rather than
something to verify separately, and any typo that adds, drops or alters a character is caught by
construction rather than by a length count that a compensating typo could satisfy.

Adding it as a mode would also have meant editing an instrument mid-series. _mkvariant_rename.py
produced the ledger name-swap variant that is already graded; changing it now would mean re-taking
that baseline for no reason. A sibling tool touches nothing.

WHAT IT REFUSES
    not a transposition  the new phrase is not a reordering of the old one's characters. That is
                         a rewrite, not a swap, and it belongs in a different row of the series —
                         the whole point of this edit kind is that NOTHING was added or removed.
    old occurs 0         the variant would equal the source: measures nothing while looking like
                         the cleanest possible null. Same distinction _asdrawn_diff.py draws
                         between a null RESULT and a null EDIT.
    old occurs >1        not a single-variable manipulation.
    new occurs >0        the target text already exists elsewhere; the arm stops being one edit.
    out exists           a silently overwritten variant is an arm graded against the wrong input.

⚠️ IT CANNOT TELL YOU THE SWAP IS SEMANTICALLY INERT. "strconv, strings" -> "strings, strconv" is
inert because Go sorts imports and the SET is what the spec means; a transposition of two operands
in an algorithm would not be. That judgement is the caller's and belongs in the pre-registration.
This tool only guarantees that nothing was added, dropped or altered.
"""
from __future__ import annotations

import pathlib
import sys


def plan(src: str, old: str, new: str) -> tuple[str, list[str]]:
    """Return (variant_text, notes) or raise ValueError naming the refusal."""
    if old == new:
        raise ValueError("old and new are identical: the variant would be the source.")
    if sorted(old) != sorted(new):
        raise ValueError(
            f"not a transposition: {old!r} and {new!r} do not contain the same characters. "
            "This edit kind exists to add and remove NOTHING."
        )

    n_old, n_new = src.count(old), src.count(new)
    if n_old == 0:
        raise ValueError(f"{old!r} does not occur in the source.")
    if n_old > 1:
        raise ValueError(f"{old!r} occurs {n_old}x — not a single-variable manipulation.")
    if n_new > 0:
        raise ValueError(f"{new!r} already occurs {n_new}x in the source.")

    out = src.replace(old, new)

    # Post-conditions. A transformation that satisfies its preconditions can still be wrong, and
    # both units are checked because they are different numbers on a non-ASCII spec: ledger.yaml
    # is 24735 characters and 24813 bytes. Reported in both, so `wc -c` can confirm it.
    if len(out) != len(src):
        raise ValueError(f"char count moved {len(src)} -> {len(out)}.")
    if len(out.encode()) != len(src.encode()):
        raise ValueError(f"byte count moved {len(src.encode())} -> {len(out.encode())}.")
    if sorted(out) != sorted(src):
        raise ValueError("the variant is not a character-level reordering of the source.")
    if out == src:
        raise ValueError("variant is identical to the source.")
    if out.count(new) != 1 or out.count(old) != 0:
        raise ValueError(f"variant has {out.count(new)}x new and {out.count(old)}x old, want 1 and 0.")

    return out, [
        f"{len(src)} chars before == {len(out)} after",
        f"{len(src.encode())} bytes before == {len(out.encode())} after  (`wc -c` agrees)",
        "whole-file character multiset UNCHANGED — nothing added, dropped or altered",
        "1 substitution, 0 left behind",
    ]


def _self_test() -> int:
    base = "a: import exactly strconv, strings,\nb: keep strconv alone\n"
    fails = []

    def want_refuse(src, old, new, label, needle):
        try:
            plan(src, old, new)
        except ValueError as e:
            if needle not in str(e):
                fails.append(f"{label}: refused for the wrong reason ({e})")
            return
        fails.append(f"{label}: ACCEPTED, should have refused")

    # Happy path: a true transposition of two equal-length words.
    try:
        out, _ = plan(base, "strconv, strings", "strings, strconv")
        if len(out) != len(base):
            fails.append("happy: length moved")
        if sorted(out) != sorted(base):
            fails.append("happy: character multiset changed")
        if "b: keep strconv alone" not in out:
            fails.append("happy: disturbed text outside the target phrase")
    except ValueError as e:
        fails.append(f"happy: refused unexpectedly ({e})")

    # A transposition of UNEQUAL-length words is still a valid transposition of the PHRASE.
    # This is the case a naive per-word length check would wrongly reject.
    try:
        out, _ = plan("x: (errors, fmt, strings)\n", "errors, fmt", "fmt, errors")
        if sorted(out) != sorted("x: (errors, fmt, strings)\n"):
            fails.append("unequal-words: multiset changed")
    except ValueError as e:
        fails.append(f"unequal-words: refused unexpectedly ({e})")

    want_refuse(base, "strconv, strings", "strings, strconvX", "notanagram", "not a transposition")
    want_refuse(base, "strconv, strings", "strconv, strings", "identity", "identical")
    want_refuse(base, "nosuchphrase here", "here nosuchphrase", "absent", "does not occur")
    want_refuse("p: ab cd\nq: ab cd\n", "ab cd", "cd ab", "twice", "occurs 2x")
    want_refuse("p: ab cd\nq: cd ab\n", "ab cd", "cd ab", "collision", "already occurs")
    # A "swap" that silently drops a character: same words, one letter short.
    want_refuse(base, "strconv, strings", "strings, strcon", "dropped", "not a transposition")

    if fails:
        print("SELF-TEST FAILED")
        for f in fails:
            print("  ✗", f)
        return 1
    print("self-test OK: 8 cases (happy, unequal-words, notanagram, identity, absent, twice, "
          "collision, dropped)")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--self-test"]:
        return _self_test()
    if len(argv) != 4:
        print('usage: _mkvariant_swap.py <src.yaml> <out.yaml> "<old phrase>" "<new phrase>"')
        return 2
    src_p, out_p, old, new = argv
    if pathlib.Path(out_p).exists():
        print(f"REFUSING: {out_p} already exists. Overwriting it would silently re-aim an arm.")
        return 3
    try:
        out, notes = plan(pathlib.Path(src_p).read_text(), old, new)
    except ValueError as e:
        print(f"REFUSING: {e}")
        return 4
    pathlib.Path(out_p).write_text(out)
    print(f"wrote {out_p}: {old!r} -> {new!r}")
    for n in notes:
        print(f"  {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
