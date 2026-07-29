#!/usr/bin/env python3
"""What did the FIX LOOP change, file by file — and did it touch what the tests ASSERT?

    python _what_the_loop_changed.py generated/taskapipro-preedit
    python _what_the_loop_changed.py --self-test

WHY. A tree on disk is the post-repair tree, and until 18:17 today there was nothing to diff
it against. `<out>/.pre-fix.json` holds every file exactly as the model wrote it, before the
first check, so the loop's own edits are now visible as a diff rather than inferred.

THE QUESTION THIS IS FOR, and it went unresolved all day: "did the repair work on the
assertion, or did it MIRROR a neighbouring file?" That was asked of taskapipro's paging twins
at 13:00, called unidentifiable at 16:00, and stayed that way because the as-drawn side did
not exist. It does now.

WHAT IT SEPARATES, because "the file changed" is too coarse to answer anything:

    UNTOUCHED       byte-identical. The tree's content for this file IS the draw's.
    FORMAT-ONLY     changed, but no assertion line differs — goimports-class. Safe to read
                    the tree as the draw for any assertion question.
    ASSERTIONS      an assertion line differs. THE TREE NO LONGER SAYS WHAT THE DRAW SAID,
                    and any claim about what this draw asserted must come from the snapshot.
    ADDED / REMOVED the loop created or deleted the file outright.

An ASSERTION LINE is one carrying t.Errorf, t.Fatalf, t.Error, t.Fatal, or a length/equality
comparison of the shape the paging witnesses use. Deliberately broad: a false ASSERTIONS
verdict costs a look at a diff, while a false FORMAT-ONLY would license exactly the mistake
this exists to prevent.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ASSERTISH = re.compile(r"t\.(Errorf|Fatalf|Error|Fatal)\(|len\([^)]*\)\s*[!=<>]=|"
                       r"\bwant\b|\bgot\b|StatusCode\s*[!=]=")


def assertion_lines(src: str) -> list[str]:
    return [ln.strip() for ln in src.splitlines() if ASSERTISH.search(ln)]


def classify(before: str | None, after: str | None) -> tuple[str, str]:
    if before is None:
        return "ADDED", "the loop created this file; it is not in the snapshot"
    if after is None:
        return "REMOVED", "the loop deleted this file after the model wrote it"
    if before == after:
        return "UNTOUCHED", "byte-identical — the tree IS the draw for this file"
    ab, aa = assertion_lines(before), assertion_lines(after)
    if ab == aa:
        b, a = len(before.splitlines()), len(after.splitlines())
        return "FORMAT-ONLY", (f"changed ({b} -> {a} lines) but every assertion line is "
                               f"identical")
    added = [l for l in aa if l not in ab]
    gone = [l for l in ab if l not in aa]
    return "ASSERTIONS", (f"{len(gone)} assertion line(s) removed, {len(added)} added — the "
                          f"tree does NOT say what the draw said")


def report(tree: pathlib.Path) -> dict:
    snap = tree / ".pre-fix.json"
    if not snap.is_file():
        return {"error": f"{snap} does not exist — this draw predates the pre-repair snapshot, "
                         f"so what the loop changed is not recoverable"}
    before = json.loads(snap.read_text())
    after = {}
    for p in tree.rglob("*"):
        if p.is_file() and p.name != ".pre-fix.json":
            try:
                after[str(p.relative_to(tree))] = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
    rows = []
    for rel in sorted(set(before) | set(after)):
        verdict, why = classify(before.get(rel), after.get(rel))
        rows.append((rel, verdict, why))
    return {"rows": rows, "before": before, "after": after}


def self_test() -> int:
    fails = []
    t = 'package x\n\nfunc TestA(t *testing.T) {\n\tif len(got) != 3 {\n\t\tt.Errorf("want 3")\n\t}\n}\n'
    if classify(t, t)[0] != "UNTOUCHED":
        fails.append("identical content is UNTOUCHED")
    # goimports-class: an import added, assertions untouched -> FORMAT-ONLY
    fmt = t.replace("package x\n", 'package x\n\nimport "testing"\n')
    if classify(t, fmt)[0] != "FORMAT-ONLY":
        fails.append(f"an added import with untouched assertions is FORMAT-ONLY, got {classify(t, fmt)}")
    # THE CASE THIS TOOL EXISTS FOR: the loop weakens the assertion.
    weak = t.replace("len(got) != 3", "len(got) != 1")
    v, why = classify(t, weak)
    if v != "ASSERTIONS":
        fails.append(f"a changed assertion bound must be ASSERTIONS, got {v}")
    if "1 assertion line(s) removed, 1 added" not in why:
        fails.append(f"it must say WHAT changed, not just that something did: {why}")
    # A DELETED assertion, which is the drained-body gate's failure mode.
    gone = t.replace('\t\tt.Errorf("want 3")\n', "")
    if classify(t, gone)[0] != "ASSERTIONS":
        fails.append("removing an assertion outright must be ASSERTIONS, not FORMAT-ONLY")
    if classify(None, t)[0] != "ADDED" or classify(t, None)[0] != "REMOVED":
        fails.append("files the loop created or deleted must be named as such")
    # Comment-only edits must NOT read as assertion changes — the inert-vs-v5 difference was
    # exactly a comment, and calling that an assertion change would have been a false alarm.
    cmt = t.replace("package x\n", "package x\n// note\n")
    if classify(t, cmt)[0] != "FORMAT-ONLY":
        fails.append("a comment-only edit is FORMAT-ONLY")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — untouched/format-only/assertions separated, a weakened bound "
                           "and a deleted assertion both flagged, comments are not assertions"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if [a for a in sys.argv[1:] if a.startswith("-")]:
        raise SystemExit("REFUSING: takes --self-test or a tree.")
    if not args:
        raise SystemExit(__doc__)
    rc = 0
    for a in args:
        r = report(pathlib.Path(a))
        print(f"\n{a}")
        if "error" in r:
            print(f"  — {r['error']}")
            rc = 1
            continue
        counts = {}
        for rel, verdict, why in r["rows"]:
            counts[verdict] = counts.get(verdict, 0) + 1
            if verdict != "UNTOUCHED":
                print(f"  {verdict:<12} {rel:<40} {why}")
        print(f"\n  " + " · ".join(f"{v} {n}" for v, n in sorted(counts.items())))
        if counts.get("ASSERTIONS"):
            print("  ⚠ For those files the TREE IS NOT THE DRAW. Any claim about what this")
            print("    draw asserted must be read from .pre-fix.json, not from disk.")
    raise SystemExit(rc)
