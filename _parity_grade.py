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


def grade(tree: str | pathlib.Path) -> dict:
    d = pathlib.Path(tree)
    s, m = d / "internal/store/store.go", d / "internal/store/memory.go"
    if not s.exists() or not m.exists():
        return {"tree": d.name, "verdict": "NO TREE", "store": "", "memory": "", "extra": []}
    st, mm = s.read_text(), m.read_text()
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
    if not trees:
        print(__doc__)
        return 2
    print(f"  {'tree':34s} {'verdict':>13s} {'store':>8s} {'memory':>8s}   beyond the interface")
    for t in trees:
        g = grade(t)
        extra = ", ".join(g["extra"][:6]) + ("…" if len(g["extra"]) > 6 else "")
        print(f"  {g['tree']:34s} {g['verdict']:>13s} {g['store']:>8s} {g['memory']:>8s}   {extra or '(none)'}")
    print("\n  VERDICT is the pre-registered endpoint. 'beyond the interface' is ADVISORY — it exposes")
    print("  the known blind spot (a store.go taking the sentinels but not MemStore grades SPLIT).")
    return 0


def self_test() -> int:
    import tempfile

    ok = True

    def mk(root: pathlib.Path, store: str, memory: str) -> pathlib.Path:
        d = root / "internal/store"
        d.mkdir(parents=True)
        (d / "store.go").write_text(store)
        (d / "memory.go").write_text(memory)
        return root

    def chk(name: str, got, want) -> None:
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: {got!r} != {want!r}")

    IFACE = "package store\n\ntype Store interface {\n\tGet(id string) error\n}\n"
    IMPL = ("package store\n\ntype MemStore struct{}\n\n"
            "func (m *MemStore) Get(id string) error { return nil }\n")

    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        a = mk(root / "split", IFACE, IMPL)
        b = mk(root / "consolidated", IFACE + IMPL.replace("package store\n\n", ""), "package store\n")
        chk("interface + sibling impl -> SPLIT", grade(a)["verdict"], "SPLIT")
        chk("everything in store.go -> CONSOLIDATED", grade(b)["verdict"], "CONSOLIDATED")
        chk("empty memory.go is not SPLIT", grade(b)["memory"], "14B")

        # THE KNOWN BLIND SPOT, asserted rather than described: sentinels taken, MemStore not.
        c = mk(root / "sentinels", IFACE + '\nvar ErrNotFound = errors.New("nf")\n', IMPL)
        chk("sentinel theft still grades SPLIT", grade(c)["verdict"], "SPLIT")
        chk("...but the advisory column NAMES it", "ErrNotFound" in grade(c)["extra"], True)
        chk("a clean interface has no extras", grade(a)["extra"], [])

        d = mk(root / "missing", IFACE, IMPL)
        (d / "internal/store/memory.go").unlink()
        chk("missing file -> NO TREE, not a verdict", grade(d)["verdict"], "NO TREE")

    print("  self-test: OK — endpoint preserved, blind spot exposed by the advisory column only"
          if ok else "  self-test: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(main(sys.argv[1:]))
