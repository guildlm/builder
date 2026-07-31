#!/usr/bin/env python3
"""Does `_fill_empty_planned_files` actually FIX the tree, or does its own check revert it?

    python _repair_survival.py [--limit N] [--specs a,b] [--out FILE]
    python _repair_survival.py --self-test

Pre-registration: logs/PREREG-does-the-repair-survive-the-green-check.txt.

`_repair_take_audit.py` answers what the repair would TRY to move. This runs it. For each tree
carrying an empty planned .go file: record whether the tree is green BEFORE, run the pass exactly
as builder.py calls it, and record the outcome.

    FILLED      moved, and toolchain.check passed afterwards
    REVERTED    moved, check failed, the pass put it back (it is strictly non-regressing)
    NO-DONOR    take was empty — nothing to try

⚠️ generated/ IS NEVER TOUCHED. Every tree is copied to a scratch directory first and the pass runs
against the copy. This is not caution for its own sake: a destructive command run beside a live
build already cost that build its files once this campaign.

⚠️ AND THE SPLIT IS THE RESULT, NOT THE RATE. Green-before and red-before are reported separately
and a combined rate is deliberately not printed — one number over both describes neither.

⚠️ THE GATE UNDER TEST CHANGED AFTER THE FIRST RUN, so the two runs are not the same experiment.
The first (logs/repair-survival.tsv, 74 cases) measured the GREEN-REQUIRING gate: the pass demanded
the whole project be green after the move, so all 59 red-tree cases reverted on evidence that had
nothing to do with the move. The gate is now NON-REGRESSING (no error the project did not already
have), and the first run is the baseline the second is scored against.
"""
# selftest: slow — the self-test builds two real trees and runs the Go toolchain on
# each (3.7s measured). --fast skips it so a corpus sweep never competes with a draw.
from __future__ import annotations

import argparse
import importlib.util
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))
import builder  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "rta", pathlib.Path(__file__).resolve().parent / "_repair_take_audit.py"
)
rta = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rta)


def run_tree(root: pathlib.Path, scratch: pathlib.Path, toolchain) -> list[dict]:
    """Copy, check, repair, check. Returns one record per empty planned file."""
    spec_path = rta.spec_for(root.name)
    if spec_path is None:
        return []
    spec = builder.Spec.from_yaml(spec_path)
    written = rta.read_tree(root, as_drawn=False)
    empty_before = builder.empty_go_files(written)
    if not empty_before:
        return []

    work = scratch / root.name
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(root, work)
    green_before, _ = toolchain.check(work)

    # the pass mutates `written` and the tree in place; both are copies
    builder._fill_empty_planned_files(spec, written, work, toolchain)
    empty_after = set(builder.empty_go_files(written))
    green_after, _ = toolchain.check(work)

    takes = {c["path"]: c for c in rta.classify(spec, rta.read_tree(root, False), True)}
    records = []
    for path in empty_before:
        take = takes.get(path, {}).get("take") or set()
        if not take:
            outcome = "NO-DONOR"
        elif path not in empty_after:
            outcome = "FILLED"
        else:
            outcome = "REVERTED"
        records.append({
            "tree": root.name, "path": path, "outcome": outcome,
            "green_before": green_before, "green_after": green_after,
            "take": sorted(take),
        })
    shutil.rmtree(work, ignore_errors=True)
    return records


def report(args) -> int:
    toolchain = builder.GoToolchain()
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="repair-survival-"))
    roots = [
        p for p in sorted(rta.GENERATED.iterdir())
        if p.is_dir() and (not args.specs or any(s in p.name for s in args.specs))
    ]
    records: list[dict] = []
    done = 0
    for root in roots:
        if args.limit and done >= args.limit:
            break
        got = run_tree(root, scratch, toolchain)
        if got:
            done += 1
            records += got
            for r in got:
                print(f"  {r['outcome']:9s} green_before={str(r['green_before']):5s} "
                      f"{r['tree']:30s} {r['path']:34s} take={r['take']}", flush=True)
    shutil.rmtree(scratch, ignore_errors=True)

    print()
    for green in (True, False):
        rows = [r for r in records if r["green_before"] is green]
        if not rows:
            continue
        label = "GREEN-BEFORE" if green else "RED-BEFORE  "
        counts = {o: sum(1 for r in rows if r["outcome"] == o) for o in
                  ("FILLED", "REVERTED", "NO-DONOR")}
        print(f"{label}  {len(rows)} cases · FILLED {counts['FILLED']} · "
              f"REVERTED {counts['REVERTED']} · NO-DONOR {counts['NO-DONOR']}")
    print(f"\n{len(records)} cases over {done} trees. No combined rate is printed on purpose: "
          f"the two populations are not the same experiment.")
    if args.out:
        pathlib.Path(args.out).write_text(
            "\n".join(f"{r['outcome']}\t{r['green_before']}\t{r['tree']}\t{r['path']}\t"
                      f"{','.join(r['take'])}" for r in records) + "\n"
        )
    return 0


def self_test() -> int:
    """A tree the move fixes, and a tree broken for an unrelated reason.

    ⚠️ THE SECOND CASE FLIPPED, AND THAT IS THE POINT. It asserted REVERTED, because the
    pass required the whole project to be green after the move. Under the non-regressing
    gate the same tree comes back FILLED: the move introduces no error the project did not
    already have, so the unrelated breakage is no longer its problem. Rewritten rather than
    deleted, so the flip is recorded where the old expectation was — an instrument that
    silently agrees with whatever the code now does is worth nothing.
    """
    import shutil as _shutil
    if _shutil.which("go") is None:
        print("self-test: SKIPPED (needs the Go toolchain)")
        return 0
    store = (
        "package store\n\ntype Store interface{ Get(id string) string }\n\n"
        "type MemStore struct{ items map[string]string }\n\n"
        "func NewMemStore() *MemStore { return &MemStore{items: map[string]string{}} }\n\n"
        "func (m *MemStore) Get(id string) string { return m.items[id] }\n"
    )
    spec = builder.Spec.from_dict({
        "name": "t", "description": "t", "go_module": "guildlm.dev/t",
        "files": [
            {"path": "store/store.go", "purpose": "Declares the Store interface."},
            {"path": "store/memory.go", "purpose": "Implements the `MemStore` type."},
        ],
    })
    toolchain = builder.GoToolchain()
    failures = 0
    for name, extra, want in (
        ("clean", None, "FILLED"),
        # unrelated breakage in ANOTHER package: the move is still clean, so the
        # non-regressing gate accepts it where the green-requiring gate refused
        ("broken-elsewhere", ("bad/bad.go", "package bad\n\nfunc F() { undefinedCall() }\n"),
         "FILLED"),
    ):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"rs-self-{name}-"))
        tree = tmp / "tree"
        (tree / "store").mkdir(parents=True)
        (tree / "go.mod").write_text("module guildlm.dev/t\n\ngo 1.22\n")
        (tree / "store" / "store.go").write_text(store)
        (tree / "store" / "memory.go").write_text("package store\n")
        if extra:
            path, content = extra
            (tree / path).parent.mkdir(parents=True, exist_ok=True)
            (tree / path).write_text(content)
        written = rta.read_tree(tree, False)
        builder._fill_empty_planned_files(spec, written, tree, toolchain)
        got = "FILLED" if "store/memory.go" not in builder.empty_go_files(written) \
            else "REVERTED"
        if got != want:
            failures += 1
            print(f"FAIL {name}: got {got}, want {want}")
        _shutil.rmtree(tmp, ignore_errors=True)
    print("self-test:", "OK — the move lands on a clean tree, and on a tree broken "
          "elsewhere (which the green-requiring gate refused)"
          if not failures else f"{failures} FAILED")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--specs", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    args.specs = [x for x in args.specs.split(",") if x]
    if args.self_test:
        return self_test()
    return report(args)


if __name__ == "__main__":
    raise SystemExit(main())
