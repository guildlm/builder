#!/usr/bin/env python3
"""Grade a ledger draw SPLIT vs CONSOLIDATED — the pre-registered parity endpoint.

    ./_parity_grade.py <tree> [<tree> ...]
    ./_parity_grade.py --self-test

THE ENDPOINT IS UNCHANGED AND DELIBERATELY SO. It is exactly what
logs/PREREG-withhold-the-parity-clause-from-an-interface-only-file.txt fixed before the switch
existed: store.go must NOT declare MemStore, and memory.go must not be empty. Extracting the
grader from _parity_ab.sh must not quietly redefine what was pre-registered, so the verdict
column here is byte-for-byte the same rule.

WHAT IS NEW IS A SECOND COLUMN, AND IT IS NOT THE ENDPOINT. The 31 July result recorded a real
blind spot in this rule:

    "_parity_ab.sh decides SPLIT vs CONSOLIDATED by asking whether store.go declares MemStore. A
    store.go that took the SENTINELS but not MemStore would grade SPLIT while still violating
    'the interface only'."

That is not hypothetical — the arm's store.go took ErrNotFound and ErrExists, which ledger's spec
does not assign to it at all. So EXTRA reports every top-level declaration in store.go beyond the
interface. It is reported alongside the verdict, never folded into it: changing an endpoint after
seeing data is how a campaign talks itself into a result, and this endpoint has already refuted
one prediction in the opposite direction.
"""
from __future__ import annotations

import pathlib
import re
import sys

# the pre-registered rule, unchanged
_DECL = re.compile(r"^\s*type\s+MemStore\b|^\s*func\s+\(\w+\s+\*?MemStore\)", re.M)
# every top-level declaration, for the advisory column
_TOP = re.compile(r"^(?:type|func|var|const)\s+\(?\s*(\w+)", re.M)
_METHOD = re.compile(r"^func\s+\(\w+\s+\*?(\w+)\)\s+(\w+)", re.M)


# ⚠️⚠️ AS-DRAWN BY DEFAULT, AND THIS IS NOT A PREFERENCE. Measured 31 July on arm-4, the first
# draw taken after the timestamp fix unblocked the repair:
#
#     AS-DRAWN   store 2263B 7f2e9f83   memory   14B     <- what the MODEL wrote: CONSOLIDATED
#     ON DISK    store  468B 33eb663c   memory 1928B     <- after the repair moved MemStore: SPLIT
#
# The same tree grades CONSOLIDATED or SPLIT depending on which state you read. Before the fix the
# repair was refused on timestamp noise, so on-disk and as-drawn agreed and the distinction was
# invisible; the fix made the two diverge. An on-disk grader now reports SPLIT for a draw the model
# consolidated — it would measure the REPAIR and report it as the model's behaviour, which is
# exactly the mistake that cost two hours and eight retracted findings on 31 July.
#
# IT REFUSES RATHER THAN FALLING BACK, the same rule _asdrawn_diff.py follows: a tree with no
# snapshot gets NO SNAPSHOT, never a quietly on-disk answer wearing an as-drawn label.
def _read(d: pathlib.Path, rel: str, on_disk: bool) -> str | None:
    if on_disk:
        p = d / rel
        return p.read_text() if p.exists() else None
    snap = d / ".pre-fix.json"
    if not snap.exists():
        return None
    import json
    files = json.loads(snap.read_text())
    files = files.get("files", files)
    return files.get(rel)


def grade(tree: str | pathlib.Path, on_disk: bool = False) -> dict:
    d = pathlib.Path(tree)
    st = _read(d, "internal/store/store.go", on_disk)
    mm = _read(d, "internal/store/memory.go", on_disk)
    if st is None or mm is None:
        no = "NO TREE" if on_disk else "NO SNAPSHOT"
        return {"tree": d.name, "verdict": no, "store": "", "memory": "", "extra": []}
    split_ok = not _DECL.search(st) and bool(_DECL.search(mm))
    names = set(_TOP.findall(st)) | {f"{r}.{n}" for r, n in _METHOD.findall(st)}
    extra = sorted(n for n in names if n not in {"Store"})
    return {
        "tree": d.name,
        "verdict": "SPLIT" if split_ok else "CONSOLIDATED",
        "store": f"{len(st)}B",
        "memory": f"{len(mm)}B",
        "extra": extra,
    }


def main(argv: list[str]) -> int:
    trees = [a for a in argv if not a.startswith("-")]
    on_disk = "--on-disk" in argv
    if not trees:
        print(__doc__)
        return 2
    state = "ON DISK (post-repair)" if on_disk else "AS DRAWN (from .pre-fix.json)"
    print(f"  state: {state}")
    print(f"  {'tree':34s} {'verdict':>13s} {'store':>8s} {'memory':>8s}   beyond the interface")
    for t in trees:
        g = grade(t, on_disk)
        extra = ", ".join(g["extra"][:6]) + ("…" if len(g["extra"]) > 6 else "")
        print(f"  {g['tree']:34s} {g['verdict']:>13s} {g['store']:>8s} {g['memory']:>8s}   {extra or '(none)'}")
    print("\n  VERDICT is the pre-registered endpoint. 'beyond the interface' is ADVISORY — it exposes")
    print("  the known blind spot (a store.go taking the sentinels but not MemStore grades SPLIT).")
    if on_disk:
        print("  ⚠️ --on-disk grades the REPAIRED tree. Since the 31 July timestamp fix the repair")
        print("  actually succeeds, so this can report SPLIT for a draw the model CONSOLIDATED.")
    return 0


def self_test() -> int:
    import json
    import tempfile

    ok = True

    def mk(root: pathlib.Path, store: str, memory: str, snap: tuple | None = None) -> pathlib.Path:
        """Write a tree on disk, and optionally a DIFFERENT .pre-fix.json — which is the whole
        point: after the 31 July timestamp fix the repair succeeds, so the two states diverge."""
        d = root / "internal/store"
        d.mkdir(parents=True)
        (d / "store.go").write_text(store)
        (d / "memory.go").write_text(memory)
        ss, sm = snap if snap else (store, memory)
        (root / ".pre-fix.json").write_text(json.dumps(
            {"internal/store/store.go": ss, "internal/store/memory.go": sm}))
        return root

    def chk(name: str, got, want) -> None:
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: {got!r} != {want!r}")

    IFACE = "package store\n\ntype Store interface {\n\tGet(id string) error\n}\n"
    IMPL = ("package store\n\ntype MemStore struct{}\n\n"
            "func (m *MemStore) Get(id string) error { return nil }\n")
    CONSOL = IFACE + IMPL.replace("package store\n\n", "")

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        a = mk(root / "split", IFACE, IMPL)
        b = mk(root / "consolidated", CONSOL, "package store\n")
        chk("interface + sibling impl -> SPLIT", grade(a)["verdict"], "SPLIT")
        chk("everything in store.go -> CONSOLIDATED", grade(b)["verdict"], "CONSOLIDATED")
        chk("empty memory.go is not SPLIT", grade(b)["memory"], "14B")

        # THE KNOWN BLIND SPOT, asserted rather than described: sentinels taken, MemStore not.
        c = mk(root / "sentinels", IFACE + '\nvar ErrNotFound = errors.New("nf")\n', IMPL)
        chk("sentinel theft still grades SPLIT", grade(c)["verdict"], "SPLIT")
        chk("...but the advisory column NAMES it", "ErrNotFound" in grade(c)["extra"], True)
        chk("a clean interface has no extras", grade(a)["extra"], [])

        # ── THE TRAP arm-4 EXPOSED: the repair split a tree the model consolidated ──
        r = mk(root / "repaired", IFACE, IMPL, snap=(CONSOL, "package store\n"))
        chk("repaired tree AS-DRAWN -> CONSOLIDATED", grade(r)["verdict"], "CONSOLIDATED")
        chk("repaired tree ON-DISK  -> SPLIT", grade(r, on_disk=True)["verdict"], "SPLIT")
        chk("the two states DISAGREE", grade(r)["verdict"] != grade(r, on_disk=True)["verdict"], True)

        # no snapshot must REFUSE, not fall back to disk wearing an as-drawn label
        n = mk(root / "nosnap", IFACE, IMPL)
        (n / ".pre-fix.json").unlink()
        chk("no snapshot -> NO SNAPSHOT", grade(n)["verdict"], "NO SNAPSHOT")
        chk("...but --on-disk still answers", grade(n, on_disk=True)["verdict"], "SPLIT")

        d = mk(root / "missing", IFACE, IMPL)
        (d / "internal/store/memory.go").unlink()
        chk("missing file on disk -> NO TREE", grade(d, on_disk=True)["verdict"], "NO TREE")

    print("  self-test: OK — endpoint preserved, as-drawn vs on-disk separated, blind spot named"
          if ok else "  self-test: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(main(sys.argv[1:]))
