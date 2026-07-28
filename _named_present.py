#!/usr/bin/env python3
"""Per-draw check: is every test the spec NAMES actually in the tree?

WHY PER DRAW. A named test going unwritten is STOCHASTIC, not a dead spec sentence — measured
2026-07-28 on two independent names (taskapi's TestMalformedJSON, absent from two draws and
present in the third; taskapipro's TestListSorted, absent from draw 1 and present in 2 and 3).
The remedy for a stochastic miss is not to rewrite the sentence, it is to CHECK EACH DRAW. I
nearly rewrote a sentence that works two draws in three.

WHY THIS EXISTS ALONGSIDE _named_test_audit. That tool refuses to score an artifact when any
spec-DECLARED FILE is missing, on the sound reasoning that a run in flight looks identical to
a model refusing to write. Correct, and it means every -v4 tree is skipped now that the Chain
closure postdates them. This asks the narrower question — are the NAMES there — and gets its
safety from _corpus_state instead, so it works on a fresh draw the moment that draw lands.

    python _named_present.py                 # every generated/*-v5 tree
    python _named_present.py generated/x-v5
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _corpus_state import check

TEST = re.compile(r"\b(Test[A-Z]\w*)\b")
HERE = pathlib.Path(__file__).resolve().parent


def audit(tree: pathlib.Path) -> tuple[str, list[str]] | None:
    """(state, missing names). None when there is no spec to compare against."""
    stem = re.sub(r"-v\d+$|-chain\d*$|-mirrors\d*$", "", tree.name)
    spec = HERE / "specs" / f"{stem}.yaml"
    if not spec.is_file():
        return None
    # ASK BEFORE MEASURING. Run this against a tree mid-generation and every file not yet
    # written reports its tests MISSING — which is how an ad-hoc version of this script
    # reported taskflow as missing fifteen tests while projects_test.go was file 16 of 16.
    # A half-written tree does not look absent; it looks like a finding.
    if check(str(tree)) == "refuse":
        return ("BEING WRITTEN", [])
    named = set(TEST.findall(spec.read_text()))
    have: set[str] = set()
    for f in tree.rglob("*_test.go"):
        have |= set(re.findall(r"func (Test[A-Z]\w*)\s*\(", f.read_text(errors="replace")))
    return ("OK", sorted(named - have))


if __name__ == "__main__":
    targets = [pathlib.Path(a) for a in sys.argv[1:] if not a.startswith("-")]
    if not targets:
        targets = sorted((HERE / "generated").glob("*-v5"))
    checked = flagged = 0
    for tree in targets:
        r = audit(tree)
        if r is None:
            continue
        state, missing = r
        if state == "BEING WRITTEN":
            print(f"{tree.name:<20} SKIPPED — being written right now, not a verdict")
            continue
        checked += 1
        if missing:
            flagged += 1
            print(f"{tree.name:<20} MISSING {len(missing)}: {', '.join(missing)}")
        else:
            print(f"{tree.name:<20} all spec-named tests present")
    print(f"\n{flagged} draw(s) missing a named test, of {checked} checked")
    if not checked:
        print("nothing was checked — which is not a pass")
