#!/usr/bin/env python3
"""Assert that two specs differ ONLY where an experiment intends them to.

    ./_spec_pair_guard.py A.yaml B.yaml --only internal/models/models.go
    ./_spec_pair_guard.py --self-test

WHY THIS EXISTS. The sentinel experiment is a paired design: one spec is the baseline, one is
treated, and the entire attribution rests on the claim "the only thing that changed is the spec
text" at ONE named file. That claim is currently true because the treated spec was produced by a
one-hunk edit — but nothing was stopping the next edit to either file from quietly widening the
difference, and a paired design whose two arms differ in two places attributes the effect to the
wrong one.

⚠️ IT CHECKS THE WHOLE FILE LIST, NOT JUST THE NAMED PURPOSE. `_file_list` renders EVERY path AND
purpose into EVERY generation prompt (builder.py:1265), so a purpose edited three files away
still changes the prompt of the file under test. That is not a hypothetical: on 5 August the
sentinel edit perturbed money_test.go, which is generated BEFORE models.go. Hence: paths and
their order must match exactly, and every purpose except the named ones must be byte-identical.

⚠️ IT DOES NOT CHECK THAT THE INTENDED DIFFERENCE IS THE RIGHT ONE. It checks that no OTHER
difference exists. What the treated phrasing says is the experiment's business; this guard's
business is that it is the only thing that is said differently.
"""

import pathlib
import sys

import yaml


def load(path: str) -> dict:
    return yaml.safe_load(pathlib.Path(path).read_text())


def compare(a: dict, b: dict, allowed: set) -> list:
    """Return a list of complaint strings; empty means the pair is sound."""
    bad = []

    pa = [f.get("path") for f in a.get("files", [])]
    pb = [f.get("path") for f in b.get("files", [])]
    if pa != pb:
        # Order matters as much as membership: generation order IS the file-list order, and
        # the split defect (30 July) is an order effect.
        bad.append(f"file lists differ (paths or order): {pa} != {pb}")
        return bad

    for key in ("name", "language", "go_module", "description"):
        if a.get(key) != b.get(key):
            bad.append(f"top-level key {key!r} differs")

    for fa, fb in zip(a["files"], b["files"]):
        if fa.get("purpose") == fb.get("purpose"):
            continue
        if fa["path"] in allowed:
            continue
        bad.append(f"purpose differs at {fa['path']!r}, which is NOT in --only")

    unused = allowed - {f["path"] for f, g in zip(a["files"], b["files"])
                        if f.get("purpose") != g.get("purpose")}
    if unused:
        # An --only entry that does not actually differ means the treated spec never got the
        # edit it was supposed to get — the silent failure this pair is most exposed to.
        bad.append(f"--only named {sorted(unused)} but those purposes are IDENTICAL "
                   f"(the intended edit is missing)")
    return bad


def self_test() -> int:
    ok = True

    def chk(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: {got!r} != {want!r}")

    def spec(*purposes):
        return {"name": "x", "language": "go",
                "files": [{"path": p, "purpose": t} for p, t in purposes]}

    base = spec(("a.go", "AAA"), ("b.go", "BBB"))

    # the intended case: exactly the named purpose differs
    chk("clean pair", compare(base, spec(("a.go", "AAA"), ("b.go", "ZZZ")), {"b.go"}), [])

    # an unintended second difference must be caught
    chk("second difference caught",
        len(compare(base, spec(("a.go", "QQQ"), ("b.go", "ZZZ")), {"b.go"})), 1)

    # ⚠️ the missing-edit direction: --only names a file that did NOT change. Without this the
    # guard passes on two IDENTICAL specs and the experiment runs with no treatment at all.
    chk("missing edit caught", len(compare(base, base, {"b.go"})), 1)

    # order is a difference, not a permutation
    chk("reorder caught",
        len(compare(base, spec(("b.go", "BBB"), ("a.go", "AAA")), {"b.go"})), 1)

    # an added file is a difference
    chk("added file caught",
        len(compare(base, spec(("a.go", "AAA"), ("b.go", "BBB"), ("c.go", "CCC")), {"b.go"})), 1)

    # two allowed files, both differing, is fine
    chk("two allowed",
        compare(base, spec(("a.go", "QQQ"), ("b.go", "ZZZ")), {"a.go", "b.go"}), [])

    # a top-level description change is caught even when every purpose matches
    d1 = dict(base, description="one")
    d2 = dict(base, description="two")
    chk("description caught", len(compare(d1, d2, set())), 1)

    print("  self-test: OK" if ok else "  self-test: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    if "--only" not in sys.argv:
        raise SystemExit(__doc__)
    cut = sys.argv.index("--only")
    args = sys.argv[1:cut]          # everything BEFORE --only is positional
    only = set(sys.argv[cut + 1:])  # everything after it is a path to allow
    if len(args) != 2 or not only:
        raise SystemExit(__doc__)
    problems = compare(load(args[0]), load(args[1]), only)
    if problems:
        print(f"REFUSING: {args[0]} and {args[1]} are not a valid pair")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(1)
    print(f"OK: {args[0]} and {args[1]} differ only at {sorted(only)}")
