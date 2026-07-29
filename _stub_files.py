#!/usr/bin/env python3
"""Files the spec assigned real content to, that a draw left as a bare package clause.

    python _stub_files.py                    # every -v4/-v5 tree
    python _stub_files.py generated/foo-v5   # named trees
    python _stub_files.py --self-test

WHY THIS EXISTS. A generated file containing nothing but `package store` compiles, vets and
tests clean. Every instrument in this repo passes it: `go build` is happy, the suite is green,
the mutation sweep finds no sites in it and therefore reports nothing, and the spec audits
check test NAMES rather than file CONTENT. The artifact looks finished.

    Found 29 July by asking where a relocated mutation site went. Three v5 trees — ledger,
    taskapipro and workapi — have `internal/store/memory.go` at FOURTEEN BYTES, `package
    store` and a newline, while the spec entry for that file describes a goroutine-safe
    in-memory Store implementation with eight methods. The implementation was written into
    store.go instead.

    Those are exactly the three artifacts whose `reverse sort by ID` mutation row vanished
    from the capstone's comparable set. The site did not disappear; it moved file, because
    the CODE moved file.

WHAT IT IS NOT. Not a style check and not a "file is short" check — a legitimately small file
(a two-line helper, a var block) has declarations. This flags only files whose entire
non-comment content is the package clause, which is a file that declares NOTHING while the
spec asked it to declare something.

⚠️ AND IT DOES NOT MEAN THE ARTIFACT IS BROKEN. All three trees are red for other reasons, and
a stub file plus the implementation somewhere else still compiles. What it means is that a
mutation site the baseline measured is not where the baseline says, and any row keyed on
(artifact, FILE) silently stops joining.
"""
from __future__ import annotations

import pathlib
import re
import sys

PACKAGE_ONLY = re.compile(r"^\s*package\s+\w+\s*$")


def is_stub(text: str) -> bool:
    """True when the file declares nothing at all — package clause, comments, blanks."""
    body = [l for l in text.splitlines() if l.strip() and not l.strip().startswith("//")]
    return len(body) == 1 and bool(PACKAGE_ONLY.match(body[0]))


def scan(trees: list[pathlib.Path]) -> list[tuple[str, str, int]]:
    out = []
    for tree in trees:
        for f in sorted(tree.rglob("*.go")):
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if is_stub(txt):
                out.append((tree.name, str(f.relative_to(tree)), len(txt)))
    return out


def self_test() -> int:
    fails = []
    if not is_stub("package store\n"):
        fails.append("a bare package clause is a stub")
    if not is_stub("// generated\n\npackage store\n\n"):
        fails.append("comments and blank lines do not make a stub non-empty")
    if is_stub("package store\n\nvar X = 1\n"):
        fails.append("a file with a declaration is NOT a stub, however short — this is the "
                     "false-positive direction and it must stay closed")
    if is_stub("package store\n\nimport \"errors\"\n"):
        fails.append("an import is a declaration; flagging it would make this a style check")
    if is_stub(""):
        fails.append("an empty file has no package clause and is a different defect")
    if is_stub("package a\npackage b\n"):
        fails.append("two package clauses is not the shape this describes")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — a bare package clause is flagged, comments do not save it, "
                           "and any real declaration clears it"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if [a for a in sys.argv[1:] if a.startswith("-")]:
        raise SystemExit("REFUSING: takes --self-test or a list of trees.")
    gen = pathlib.Path(__file__).resolve().parent / "generated"
    trees = ([pathlib.Path(a) for a in args] if args
             else sorted(p for p in gen.glob("*-v[45]") if p.is_dir()))
    hits = scan(trees)
    print(f"scanned {len(trees)} tree(s)")
    if not hits:
        print("  no stub files — every generated .go declares something")
        raise SystemExit(0)
    print(f"  {len(hits)} file(s) declare NOTHING while their spec entry asked for content:\n")
    for t, f, n in hits:
        print(f"    {t:<24} {f:<34} {n}B")
    print("\n  A stub compiles, vets and tests clean, and a mutation sweep finds no sites in")
    print("  it — so it is invisible to every other instrument here. Where the content went")
    print("  instead is the question: if it moved to a sibling file, every row keyed on")
    print("  (artifact, FILE) silently stops joining across generations.")
    raise SystemExit(1)
