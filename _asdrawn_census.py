#!/usr/bin/env python3
"""Census the AS-DRAWN variety of one file across every archived tree of a project.

    ./_asdrawn_census.py ledger                              # every file, one line each
    ./_asdrawn_census.py ledger internal/models/models.go    # one file, with its hashes
    ./_asdrawn_census.py --self-test

THE QUESTION IT ANSWERS. "The process selects among a small set of stable alternatives" was
registered as a HYPOTHESIS on 31 July, about one identifier's NAME
(logs/PREREG-is-a-single-identifiers-name-a-property-of-the-process.txt). This measures the
stronger version directly: how many distinct BYTE SEQUENCES does a given file take across the
whole archive? A name is a function of the file; the file is the thing the model emits.

⚠️⚠️ AS-DRAWN ONLY, AND IT REFUSES TO FALL BACK TO DISK. Every tree here has been through a fix
loop, and reading the repaired file would count repairs as draws. That is the error class behind
the 29 July retraction, the `_parity_grade` disk read, and the 5 August "fourth file in another
package" correction — three times, so this reads `.pre-fix.json` and nothing else, and a tree
without one is reported MISSING rather than silently skipped.

⚠️⚠️ THE COUNTS ARE NOT INDEPENDENT DRAWS AND MUST NEVER BE READ AS A RATE. Six of the ledger
trees are the parity control/arm pairs, drawn BY DESIGN from one process (pid 7598) to be
compared against each other; several more are unlabelled and cannot be grouped by process at all
(the "category-2 trap" that same prereg names). So a hash appearing nine times is nine TREES, not
nine independent observations, and this tool prints that warning next to every table rather than
trusting the reader to remember it.

⚠️ THE SPECS VARIED TOO. Some archived trees were drawn from name-swap, order and prose variants
of the spec. Where such a variant edits the purpose of the file being censused, its draw is not
answering the same prompt. This tool cannot reconstruct which spec each tree used — it reports
variety, and the caveat travels with the number.
"""

import collections
import hashlib
import json
import pathlib
import sys

GEN = pathlib.Path(__file__).parent / "generated"


def as_drawn(tree: pathlib.Path) -> dict | None:
    """The write-once snapshot of what the model WROTE, or None if this tree has no snapshot."""
    snap = tree / ".pre-fix.json"
    if not snap.is_file():
        return None
    try:
        d = json.loads(snap.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    files = d.get("files") if isinstance(d, dict) else None
    return files if isinstance(files, dict) else (d if isinstance(d, dict) else None)


def census(project: str, path: str) -> tuple:
    """(rows, missing) where rows are (tree, hash12, size) for trees that DECLARE this file."""
    rows, missing = [], []
    for tree in sorted(GEN.glob("*")):
        if not tree.is_dir() or project.lower() not in tree.name.lower():
            continue
        files = as_drawn(tree)
        if files is None:
            missing.append(tree.name)
            continue
        src = files.get(path)
        if src is None:
            continue
        rows.append((tree.name, hashlib.sha256(src.encode()).hexdigest()[:12], len(src)))
    return rows, missing


def all_paths(project: str) -> list:
    seen = []
    for tree in sorted(GEN.glob("*")):
        if not tree.is_dir() or project.lower() not in tree.name.lower():
            continue
        for p in (as_drawn(tree) or {}):
            if p not in seen:
                seen.append(p)
    return seen


def self_test() -> int:
    import tempfile
    ok = True

    def chk(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: {got!r} != {want!r}")

    global GEN
    with tempfile.TemporaryDirectory() as td:
        GEN = pathlib.Path(td)

        def tree(name, files=None, snapshot=True, ondisk=None):
            d = GEN / name
            (d / "internal").mkdir(parents=True, exist_ok=True)
            if snapshot:
                (d / ".pre-fix.json").write_text(json.dumps({"files": files or {}}))
            if ondisk:
                for p, s in ondisk.items():
                    f = d / p
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_text(s)

        tree("demo-a", {"m.go": "AAA"})
        tree("demo-b", {"m.go": "AAA"})          # same bytes -> same hash
        tree("demo-c", {"m.go": "BBB"})
        tree("other-x", {"m.go": "ZZZ"})         # different project, must not be counted
        tree("demo-d", snapshot=False, ondisk={"m.go": "AAA"})  # NO snapshot, but on disk

        rows, missing = census("demo", "m.go")
        chk("counts only its own project", len(rows), 3)
        chk("identical bytes share a hash", len({h for _, h, _ in rows}), 2)

        # ⚠️ THE ONE THAT MATTERS: a tree with the file ON DISK but NO snapshot must be reported
        # MISSING, never counted. Counting it would put a REPAIRED file in a census of draws —
        # the exact substitution behind three retractions in this repo.
        chk("no-snapshot tree is MISSING, not counted", missing, ["demo-d"])
        chk("no-snapshot tree not in rows", [t for t, _, _ in rows if t == "demo-d"], [])

        # a tree whose snapshot simply lacks the file is neither counted nor 'missing'
        tree("demo-e", {"other.go": "QQQ"})
        rows2, missing2 = census("demo", "m.go")
        chk("absent-from-snapshot is skipped silently", len(rows2), 3)
        chk("absent-from-snapshot is not MISSING", missing2, ["demo-d"])

        # a corrupt snapshot must read as MISSING rather than crash the census
        (GEN / "demo-f").mkdir(parents=True, exist_ok=True)
        (GEN / "demo-f" / ".pre-fix.json").write_text("{not json")
        _, missing3 = census("demo", "m.go")
        chk("corrupt snapshot is MISSING", sorted(missing3), ["demo-d", "demo-f"])

    print("  self-test: OK" if ok else "  self-test: FAILED")
    return 0 if ok else 1


CAVEAT = ("  ⚠️ counts are TREES, not independent draws: parity pairs share a process by design "
          "and\n     unlabelled trees cannot be grouped by process at all. Never read a rate here.")

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    proj = sys.argv[1]

    if len(sys.argv) == 2:
        print(f"AS-DRAWN VARIETY across archived '{proj}' trees — distinct byte sequences per file\n")
        print(f"  {'file':<40} {'trees':>6} {'distinct':>9}  {'top':>5}")
        for p in all_paths(proj):
            rows, _ = census(proj, p)
            if not rows:
                continue
            c = collections.Counter(h for _, h, _ in rows)
            print(f"  {p:<40} {len(rows):>6} {len(c):>9}  {c.most_common(1)[0][1]:>5}")
        print("\n" + CAVEAT)
        raise SystemExit(0)

    path = sys.argv[2]
    rows, missing = census(proj, path)
    if not rows:
        raise SystemExit(f"no archived '{proj}' tree has an as-drawn {path}")
    c = collections.Counter(h for _, h, _ in rows)
    print(f"AS-DRAWN {path} across {len(rows)} '{proj}' trees -> {len(c)} distinct byte sequences\n")
    for h, n in c.most_common():
        size = next(s for _, hh, s in rows if hh == h)
        print(f"  {h}  x{n:<3} {size:>6}B")
        for t, hh, _ in rows:
            if hh == h:
                print(f"        {t}")
    if missing:
        print(f"\n  MISSING as-drawn snapshot ({len(missing)}): {', '.join(missing)}")
    print("\n" + CAVEAT)
