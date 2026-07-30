#!/usr/bin/env python3
"""Does each generated file DECLARE what its spec entry NAMES? The check `empty_go_files` is not.

⚠️⚠️ MEASURED VERDICT, 31 July 04:45: THIS TOOL ADDS NOTHING. Over 125 trees it flags a strict SUBSET
of what `empty_go_files` flags — both 62, EMPTY-only 2, OWNERSHIP-only ZERO — and it reports its own
motivating case (workapi-pairB-w1, which loses two sentinels from store.go) as CLEAN, because
`var ErrNotFound` matches neither of its patterns. See
logs/RESULT-the-ownership-check-fails-its-own-motivating-case.txt. Kept so the measurement is not
repeated, not because the check is useful.

    python _entry_ownership.py <spec.yaml> <tree> [<tree>...]
    python _entry_ownership.py --self-test

WHY THIS EXISTS, AND WHY THE EXISTING CHECK IS NOT ENOUGH.
builder.py asks one question about plan conformance: `empty_go_files` — did a planned .go file end
up declaring NOTHING. That found a real defect (58% of the corpus, measured 30 July) and it is too
coarse by exactly one step:

    workapi's reordered draw has NO empty file. store.go keeps the Store interface. And the two
    sentinels its entry names in plain words — "Exported sentinels var ErrNotFound and var ErrExists"
    — are declared in memory.go instead. `empty_go_files` scores that tree CLEAN. It is not clean.

    A file can hold SOMETHING and still not hold ITS something. Emptiness is the extreme case of a
    violation this asks about directly.

WHAT IT COMPARES
    for each entry in the spec:  the type/symbol names its purpose promises  (_required_decls,
                                 plus backticked capitalised identifiers, which is the widening
                                 simulated at 04:05 and NOT yet applied to builder.py — this tool
                                 uses it so the two can be compared before that edit is made)
    against:                     top_level_decls | method_decls of the generated file

    A name promised by the entry and declared SOMEWHERE ELSE IN THE SAME PACKAGE is the interesting
    case: that is consolidation. A name promised and declared NOWHERE is a different defect (the
    models.Event omission) and is reported separately, because conflating them is how "the stub" and
    "the missing type" got the same name for a month.

⚠️ IT READS .pre-fix.json WHEN PRESENT. Post-repair trees have had the fix loop and possibly
_fill_empty_planned_files move things; as-drawn is what the model wrote. Falls back to disk and SAYS
SO, rather than silently mixing two populations — that mistake cost a retraction on 30 July.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

_TYPE_RE = re.compile(r"(?<![.\w])([A-Z]\w*)\s+(?i:struct|interface)\b")
_TICK_RE = re.compile(r"`([A-Z]\w*)`")
_TOP_RE = re.compile(r"^(?:type|func|var|const)\s+(\w+)", re.M)
_METH_RE = re.compile(r"^func\s+\([^)]*\)\s*(\w+)", re.M)


def _pkgdir(path: str) -> str:
    """Directory of a path, "" for a top-level file. NOT rsplit("/",1)[0] — that returns the
    FILENAME for a path with no slash, so two top-level files read as different packages. The
    self-test caught this on its first run, which is the entire reason it exists."""
    return path.rsplit("/", 1)[0] if "/" in path else ""


def promised(purpose: str) -> set[str]:
    """Names the entry says this file will define."""
    return set(_TYPE_RE.findall(purpose or "")) | set(_TICK_RE.findall(purpose or ""))


def declared(code: str) -> set[str]:
    return set(_TOP_RE.findall(code or "")) | set(_METH_RE.findall(code or ""))


def entries(spec_text: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in
            re.finditer(r"  - path: (\S+)\n(.*?)(?=\n  - path:|\Z)", spec_text, re.S)}


def load(tree: pathlib.Path) -> tuple[dict[str, str], str]:
    snap = tree / ".pre-fix.json"
    if snap.exists():
        return json.load(open(snap)), "as-drawn"
    return ({str(f.relative_to(tree)): f.read_text() for f in tree.rglob("*.go")}, "post-repair")


def audit(spec_entries: dict[str, str], files: dict[str, str]) -> dict:
    """Per file: promised names that it does NOT declare, split by where they went."""
    rows = []
    for path, purpose in spec_entries.items():
        if not path.endswith(".go") or path not in files:
            continue
        # ⚠️ A NAME ANOTHER ENTRY ALSO PROMISES IS NOT THIS FILE'S. memory.go's purpose says "the
        # Store interface declared in store.go" — mentioning a sibling's type is not a claim to
        # declare it. Without this subtraction the audit reports 96% of the corpus as violating,
        # which is an artefact of counting every cross-reference as an unmet promise. builder.py's
        # own repair does the same subtraction (`take = wanted - _required_decls(donor_purpose)`);
        # this tool skipped it and I nearly published the 96%.
        others = set()
        for op, opur in spec_entries.items():
            if op != path and op.endswith(".go") and _pkgdir(op) == _pkgdir(path):
                others |= promised(opur)
        want = promised(purpose) - others
        if not want:
            continue
        have = declared(files[path])
        missing = want - have
        if not missing:
            continue
        pkg = _pkgdir(path)
        elsewhere, nowhere = set(), set()
        for name in missing:
            found = any(name in declared(c) for p, c in files.items()
                        if p != path and p.endswith(".go") and _pkgdir(p) == pkg)
            (elsewhere if found else nowhere).add(name)
        rows.append({"path": path, "consolidated": sorted(elsewhere), "absent": sorted(nowhere)})
    return {"violations": rows}


def _self_test() -> int:
    fails = []
    ents = {"a.go": "package p. `Widget` and a Thing struct.", "b.go": "package p. Nothing named."}

    # consolidation: a.go promises Widget/Thing, b.go declares them instead
    files = {"a.go": "package p\n", "b.go": "package p\ntype Widget struct{}\ntype Thing struct{}\n"}
    r = audit(ents, files)["violations"]
    if len(r) != 1 or r[0]["consolidated"] != ["Thing", "Widget"] or r[0]["absent"]:
        fails.append(f"consolidation: {r}")

    # absent: promised by a.go, declared nowhere in the package
    files = {"a.go": "package p\n", "b.go": "package p\n"}
    r = audit(ents, files)["violations"]
    if len(r) != 1 or r[0]["absent"] != ["Thing", "Widget"] or r[0]["consolidated"]:
        fails.append(f"absent: {r}")

    # clean: a.go declares what it promised
    files = {"a.go": "package p\ntype Widget struct{}\ntype Thing struct{}\n", "b.go": "package p\n"}
    if audit(ents, files)["violations"]:
        fails.append("clean tree reported a violation")

    # METHODS count as declarations — a file whose promise is satisfied by methods is not a violation
    if audit({"a.go": "package p. `Widget`."},
             {"a.go": "package p\nfunc (w x) Widget() {}\n"})["violations"]:
        fails.append("method declaration not recognised")

    # a DIFFERENT PACKAGE holding the name is NOT consolidation — it is absent from this package
    r = audit(ents, {"a.go": "package p\n", "other/b.go": "package q\ntype Widget struct{}\n"})["violations"]
    if not r or "Widget" not in r[0]["absent"]:
        fails.append(f"cross-package leak counted as consolidation: {r}")

    # an entry promising nothing is skipped, not reported as clean-with-zero
    if audit({"b.go": "package p. Nothing named."}, {"b.go": "package p\n"})["violations"]:
        fails.append("entry with no promised names should be skipped")

    if fails:
        print("SELF-TEST FAILED")
        for f in fails:
            print("  ✗", f)
        return 1
    print("self-test OK: 6 cases (consolidation, absent, clean, methods, cross-package, no-promise)")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--self-test"]:
        return _self_test()
    if len(argv) < 2:
        print("usage: _entry_ownership.py <spec.yaml> <tree> [<tree>...]")
        return 2
    ents = entries(pathlib.Path(argv[0]).read_text())
    total = viol = 0
    for t in argv[1:]:
        tree = pathlib.Path(t)
        if not tree.is_dir():
            print(f"  SKIP {t}: not a directory")
            continue
        files, src = load(tree)
        rows = audit(ents, files)["violations"]
        total += 1
        viol += 1 if rows else 0
        print(f"  {tree.name:34s} [{src}] {'CLEAN' if not rows else f'{len(rows)} file(s) violate'}")
        for r in rows:
            bits = []
            if r["consolidated"]:
                bits.append(f"CONSOLIDATED elsewhere in package: {r['consolidated']}")
            if r["absent"]:
                bits.append(f"ABSENT from the package entirely: {r['absent']}")
            print(f"      {r['path']:34s} {' · '.join(bits)}")
    print(f"\n  {viol} of {total} tree(s) violate entry ownership")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
