#!/usr/bin/env python3
"""Does a spec entry's stated test COUNT match the tests it actually names?

taskflow's projects_test.go entry described TestListProjectsSorted at the top, then said
"SIX test functions, all of them:" and listed six others. The model wrote the six the file
counted, three draws running, and the seventh test — the only thing defending the projects
sort — was never written. Three hypotheses were refuted this morning before anyone read
the count.

What the model actually follows is the ENUMERATION, not the number: taskapipro's service
entry says EIGHT and lists nine, and the tree holds nine; its router entry says TEN twice,
lists nine, and the tree holds nine. So the number disagreeing is only the flag that gets
you looking. The signal is a test NAMED IN THE ENTRY BUT NOT IN THE LIST — which is where
taskflow's went unwritten three draws running. Checkable without a GPU, over every spec.

    python _spec_count_audit.py [spec.yaml ...]   # default: every spec in specs/
    python _spec_count_audit.py --self-test

WHAT IT DOES NOT CLAIM
  A mismatch is a CANDIDATE, not a defect: an entry may legitimately mention a test that
  lives in another file ("TestListSorted only pins the TASKS sort"), and this cannot tell a
  cross-reference from an instruction. It prints both lists so the reading takes seconds.
  It says nothing about entries with no count at all — taskapipro dropped a test from an
  uncounted list, so absence of a count is not safety.
"""
from __future__ import annotations

import pathlib
import re
import sys

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
         "fourteen": 14, "fifteen": 15}
# "SIX test functions", "EXACTLY these five test functions", "TEN test functions and NO more"
# One optional adjective between the number and "test functions": the corpus writes both
# "SIX test functions" and "THREE flow test functions", and a pattern that demanded them to
# be adjacent read the second as no count at all — silently, on the entry I had just edited.
COUNT_RE = re.compile(r"\b(" + "|".join(WORDS) + r")\s+(?:\w+\s+)?test\s+functions?\b", re.I)
# "ONE TEST FUNCTION, ONE OUTCOME" is a RATE, not an inventory — it says how much each
# function may assert, not how many the file gets. Three specs carry it verbatim and all
# three were flagged as mismatches on the first run, which is three false alarms out of
# seven. A count of one is never an inventory in this corpus: an entry that wanted a single
# test would name it rather than count it.
RATE_ONLY = 1
# \w* not \w+ — the self-test's own `TestA` fixture failed to match a pattern that
# demanded a character after the capital, and a name-extractor that misses short names
# would have under-counted every entry it read.
TEST_RE = re.compile(r"\b(Test[A-Z]\w*)\b")
# `- path: x_test.go` ... `purpose: >-` blocks, split on the path key at any indent.
ENTRY_RE = re.compile(r"^\s*-\s*path:\s*(\S+)\s*$", re.M)


def entries(text: str) -> list[tuple[str, str]]:
    """(path, entry-text) for every file entry in a spec."""
    marks = [(m.group(1), m.start()) for m in ENTRY_RE.finditer(text)]
    out = []
    for i, (path, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        out.append((path, text[start:end]))
    return out


def audit_entry(path: str, body: str) -> dict | None:
    counts = [WORDS[m.group(1).lower()] for m in COUNT_RE.finditer(body)
              if WORDS[m.group(1).lower()] != RATE_ONLY]
    if not counts:
        return None
    named = list(dict.fromkeys(TEST_RE.findall(body)))
    # THE COUNT IS NOT THE SIGNAL — THE LIST IS. Measured: taskapipro's service entry says
    # EIGHT and enumerates nine, and the tree holds all nine; its router entry says TEN
    # twice, enumerates nine, and the tree holds nine. The model follows the ENUMERATION
    # and ignores the number. taskflow's dropped test was the one named OUTSIDE the
    # enumerated list, which is the shape worth flagging.
    #
    # The list is what follows the count sentence in `TestX: ...` form; anything named only
    # before it is a mention, and a mention is what went unwritten three draws running.
    m = COUNT_RE.search(body)
    # ANY form after the count, not just `TestX:`. An entry can enumerate three new tests
    # while naming the five existing ones inside the count sentence itself ("THREE MORE test
    # functions — in ADDITION to TestBucket, ... which all stay"), and those five are plainly
    # part of the inventory. Requiring a colon reported them as left out, on a spec I had
    # just written to include them. What still counts as OUTSIDE is a name that appears ONLY
    # BEFORE the count — which is exactly taskflow's shape and the reason this exists.
    listed = list(dict.fromkeys(re.findall(r"\b(Test[A-Z]\w*)", body[m.end():]))) if m else []
    outside = [t for t in named if t not in listed]
    return {"path": path, "stated": counts, "named": named, "listed": listed,
            "outside": outside, "mismatch": all(c != len(named) for c in counts)}


def audit(spec: pathlib.Path) -> list[dict]:
    return [r for r in (audit_entry(p, b) for p, b in entries(spec.read_text())) if r]


def self_test() -> int:
    fails = []
    ok_spec = """
  - path: a_test.go
    purpose: >-
      TWO test functions, all of them:
      TestA: does a thing.
      TestB: does another.
"""
    bad_spec = """
  - path: b_test.go
    purpose: >-
      TestOutsideTheList: the one that gets dropped.
      TWO test functions, all of them:
      TestA: does a thing.
      TestB: does another.
"""
    adjective = """
  - path: d_test.go
    purpose: >-
      TestOutsideTheList: dropped.
      TWO flow test functions, all of them:
      TestA: does a thing.
      TestB: does another.
"""
    no_count = """
  - path: c_test.go
    purpose: >-
      TestA: a.
      TestB: b.
"""
    got = audit_entry("a_test.go", ok_spec)
    if not got or got["mismatch"]:
        fails.append("an entry whose count matches its named tests must NOT be flagged")
    got = audit_entry("b_test.go", bad_spec)
    if not got or not got["mismatch"]:
        fails.append("the taskflow shape — a test named above the count — must be flagged")
    if got and len(got["named"]) != 3:
        fails.append(f"named tests miscounted: {got and got['named']}")
    got = audit_entry("b_test.go", bad_spec)
    if not got or got["outside"] != ["TestOutsideTheList"]:
        fails.append(f"the test named above the list must be reported as outside it: "
                     f"{got and got.get('outside')}")
    got = audit_entry("a_test.go", ok_spec)
    if got and got["outside"]:
        fails.append("an entry whose every named test is enumerated has nothing outside")
    got = audit_entry("d_test.go", adjective)
    if not got or got["outside"] != ["TestOutsideTheList"]:
        fails.append(f"'THREE flow test functions' must parse as a count: {got and got.get('outside')}")
    if audit_entry("c_test.go", no_count) is not None:
        fails.append("an entry with no count sentence must be silent, not clean")
    # Two entries in one document must not bleed into each other.
    both = [r for r in (audit_entry(p, b) for p, b in entries(ok_spec + bad_spec)) if r]
    if len(both) != 2 or both[0]["mismatch"] or not both[1]["mismatch"]:
        fails.append("entries must be split by path, not merged")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else "ok — flags the counted gap, silent on the rest"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    targets = [pathlib.Path(a) for a in sys.argv[1:] if not a.startswith("-")]
    if not targets:
        targets = sorted((pathlib.Path(__file__).resolve().parent / "specs").glob("*.yaml"))
    for t in targets:
        if not t.is_file():
            raise SystemExit(f"{t} is not a file")
    flagged = checked = 0
    for spec in targets:
        for row in audit(spec):
            checked += 1
            if not row["mismatch"]:
                continue
            flagged += 1
            print(f"\n{spec.name}  {row['path']}")
            print(f"   states  : {', '.join(str(c) for c in row['stated'])} test function(s)")
            print(f"   lists   : {len(row['listed'])} — {', '.join(row['listed'])}")
            if row["outside"]:
                print(f"   NAMED BUT NOT LISTED: {', '.join(row['outside'])}")
                print(f"      A CANDIDATE, not a verdict. taskflow's TestListProjectsSorted "
                      f"sat here and went\n      unwritten three draws running; a test that "
                      f"lives in ANOTHER file and is only\n      referred to here sits here "
                      f"too, and is fine. Check which before editing.")
            else:
                print(f"   every named test is in the list — the number disagrees, the "
                      f"enumeration does not")
    # DENOMINATOR: how many entries carried a count at all. "0 flagged" out of 0 counted
    # entries is not a clean corpus, it is an unasked question.
    print(f"\n{flagged} mismatch(es) in {checked} entr(y/ies) that state a count "
          f"({len(targets)} spec file(s) read)")
    if not checked:
        print("no entry stated a count — this audit had nothing to check, which is not a pass")
