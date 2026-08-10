#!/usr/bin/env python3
"""Which sentinel state did each archived ledger tree draw, and does it track the SPEC?

    ./_verdict_by_tree.py [project]        # default ledger
    ./_verdict_by_tree.py --self-test

THE QUESTION. The ledger archive splits about 9 LONG / 9 ABBREVIATED / 7 ABSENT, and the
campaign has read that as PROCESS variation since 31 July — different server processes declaring
the name differently. On that reading, probing fresh processes should turn up ABBREVIATED about a
third of the time. It never has: six probes on 6 August and about ten on 10 August produced only
ABSENT and LONG, and the save point flags the ABBREVIATED branch as registered-but-unrun.

Then a FIVE-CHARACTER spec edit produced ABBREVIATED on demand
(logs/RESULT-the-outcome-is-graded-and-a-five-character-edit-found-the-missing-third-state.txt).
So the archive's middle state may not be process variation at all — it may be SPEC variation,
because a good number of those trees were drawn from name/order/prose variants of the ledger spec
rather than from the baseline.

This prints the verdict per tree, next to whatever the tree's NAME says about which variant drew
it, so the two readings can be told apart instead of assumed.

⚠️⚠️ THE TREE NAME IS A HINT, NOT A RECORD. Nothing in an archived tree stores which spec drew
it — _asdrawn_census.py says so and refuses to guess. This tool does not guess either: it prints
the name, marks trees whose name contains a known variant token, and reports the rest as UNKNOWN.
A tree in the UNKNOWN bucket is not evidence for either reading.

⚠️ AS-DRAWN ONLY. Reads .pre-fix.json and never falls back to disk.
"""

import collections
import hashlib
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _sentinel_mention_census import as_drawn  # noqa: E402
from _sentinel_verdict import verdict  # noqa: E402

HERE = pathlib.Path(__file__).parent
GEN = HERE / "generated"
TARGET = "internal/models/models.go"

# tokens that appear in the NAME of a tree drawn from a non-baseline spec variant
VARIANT_TOKENS = ("name1", "name2", "name3", "order1", "prose1", "prose2", "prose",
                  "tagfix", "varonly", "jobstrip", "ownplacebo", "linedose", "ac",
                  "sentinelline", "belowline", "treated", "strip", "placebo")


def variant_of(tree_name: str) -> str:
    """Variant tokens appearing as whole hyphen/underscore-delimited SEGMENTS of the name.

    ⚠️ SEGMENTS, NOT SUBSTRINGS. The first version matched substrings and the token "ac" fired
    inside "pl-ac-ebo" — every placebo tree would have been labelled an A+C tree, which is the
    exact confusion this tool exists to prevent.
    """
    segments = set(re.split(r"[^a-z0-9]+", tree_name.lower()))
    hits = [t for t in VARIANT_TOKENS if t in segments]
    return "+".join(hits) if hits else "UNKNOWN"


def rows(project: str) -> list:
    out = []
    for tree in sorted(GEN.glob("*")):
        if not tree.is_dir() or project.lower() not in tree.name.lower():
            continue
        files = as_drawn(tree)
        if files is None or TARGET not in files:
            continue
        src = files[TARGET]
        out.append((tree.name, verdict(src), variant_of(tree.name),
                    hashlib.sha256(src.encode()).hexdigest()[:8], len(src)))
    return out


def report(project: str = "ledger") -> int:
    data = rows(project)
    if not data:
        print(f"REFUSING: no as-drawn {TARGET} found for {project!r}")
        return 2

    print(f"  {len(data)} archived {project} trees with an as-drawn {TARGET}\n")
    print(f"    {'tree':<44}{'verdict':<26}{'variant token(s)':<22}{'sha':<10}size")
    for name, v, var, sha, size in data:
        print(f"    {name:<44}{v:<26}{var:<22}{sha:<10}{size}")

    # ⚠️ PRINTED, NOT RETYPED. The first write-up of this census counted trees per file BY EYE
    # off the row list and got two of six rows wrong. A count that goes in a log is a count the
    # tool has to produce.
    print("\n  === distinct as-drawn files, by how many trees produced each ===")
    per_file: collections.Counter = collections.Counter()
    verdict_of: dict = {}
    for _, v, _, sha, size in data:
        per_file[(sha, size)] += 1
        verdict_of[(sha, size)] = v
    for (sha, size), n in sorted(per_file.items(), key=lambda kv: kv[0][1]):
        print(f"    {sha}  {size:>5}   {verdict_of[(sha, size)]:<28} {n:>2} tree(s)")
    print(f"    {'':>15}   {'':<28} {sum(per_file.values()):>2} total, "
          f"{len(per_file)} distinct sequences")

    print("\n  === verdict by whether the tree's NAME shows a spec variant ===")
    table: collections.defaultdict = collections.defaultdict(collections.Counter)
    for _, v, var, _, _ in data:
        table["UNKNOWN" if var == "UNKNOWN" else "NAMED VARIANT"][v.split(":")[0]] += 1
    for bucket in sorted(table):
        counts = table[bucket]
        total = sum(counts.values())
        parts = " · ".join(f"{k} {counts[k]}" for k in sorted(counts))
        print(f"    {bucket:<16} n={total:<4} {parts}")
    print("\n  ⚠️ UNKNOWN means the NAME carries no variant token — NOT that the baseline drew it.")
    print("  ⚠️ No tree records its spec. These buckets are a hint to be followed up, not a result.")
    return 0


def self_test() -> int:
    import json
    import tempfile

    ok = True

    def chk(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: got {got!r} want {want!r}")
        else:
            print(f"  ok   {name}")

    chk("a variant token is recognised", variant_of("ledger-prose1-2"), "prose1")
    chk("a plain name is UNKNOWN", variant_of("ledger-xproc-ctl-1"), "UNKNOWN")
    chk("multiple tokens are all reported", variant_of("probe-js-strip-placebo"),
        "strip+placebo")
    # ⚠️ The substring bug this tool was written with, pinned so it cannot come back. Note the
    # assertion is on the TOKEN LIST, not on the result string: the first version asked whether
    # "ac" appeared in the string "placebo" and failed for the same reason the bug existed.
    chk("'ac' is not among the tokens for a placebo tree",
        "ac" in variant_of("probe-x-placebo").split("+"), False)
    chk("'ac' still fires as its own segment", variant_of("probe-s-ac"), "ac")

    long_src = 'package m\n\nvar (\n\tErrInsufficientFunds = errors.New("x")\n)\n'
    abbr_src = 'package m\n\nvar (\n\tErrInsufficient = errors.New("x")\n)\n'
    none_src = 'package m\n\nvar (\n\tErrNotFound = errors.New("x")\n)\n'
    chk("verdicts come from the shared classifier",
        (verdict(long_src), verdict(abbr_src), verdict(none_src)),
        ("LONG", "ABBREVIATED:ErrInsufficient", "ABSENT"))

    with tempfile.TemporaryDirectory() as td:
        global GEN
        old = GEN
        GEN = pathlib.Path(td)
        for nm, src in (("ledger-a", long_src), ("ledger-prose1-b", abbr_src)):
            d = GEN / nm
            d.mkdir()
            (d / ".pre-fix.json").write_text(json.dumps({TARGET: src}))
        (GEN / "ledger-nosnap").mkdir()
        got = rows("ledger")
        GEN = old
        chk("a tree without a snapshot is skipped, not guessed", len(got), 2)
        chk("rows carry verdict and variant",
            sorted((r[0], r[1], r[2]) for r in got),
            [("ledger-a", "LONG", "UNKNOWN"),
             ("ledger-prose1-b", "ABBREVIATED:ErrInsufficient", "prose1")])

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    sys.exit(report(sys.argv[1] if len(sys.argv) > 1 else "ledger"))
