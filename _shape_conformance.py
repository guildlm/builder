#!/usr/bin/env python3
"""The spec asked for a STRUCT and the draw declared an INTERFACE. Nothing else notices.

    python _shape_conformance.py            # every spec against its -v4/-v5 trees
    python _shape_conformance.py taskflow   # named specs
    python _shape_conformance.py --self-test

WHY. specs/taskflow.yaml's store entry says "A Store STRUCT holding two maps ... built by
NewStore()". Every taskflow draw for weeks has produced `type Store interface` and put the
maps in a second type the spec never mentions — StoreImpl in most draws, `store` in the one
that got twelve extra lines of prose. All of them converged GREEN.

    A green suite tests BEHAVIOUR. The shape of the type it went through is invisible to it,
    to `go vet`, to the mutation sweep, and to the spec audits here, which check test names and
    promised guards. So a draw can restructure the package's type design away from what the
    spec asked for and every instrument in this repo passes it.

WHY THIS ONE IS WORTH HAVING AND THE SYMBOL-PLACEMENT AUDIT WAS NOT. That one (declined 18:36,
see NOTE-spec-symbol-placement-audit-declined.txt) fired 39 times to surface 3 real hits,
because a spec entry MENTIONS symbols it merely uses. This asks a much narrower question:
    the spec says "<Name> struct" AND the tree declares "type <Name> interface" AND
    it does NOT also declare "type <Name> struct"
Measured across the whole corpus: 101 spec-named structs checked, 4 flagged, all four the same
real defect, no false positives.

WHAT IT DELIBERATELY DOES NOT FLAG
  * a name the tree does not declare at all — that is ABSENCE, a different defect, and one a
    compile failure already catches;
  * a name declared as BOTH (some specs describe an interface and a struct of similar name);
  * a struct declared under a different name — that is the symbol-placement question, which
    is not reliably answerable from prose.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

STRUCT_IN_PROSE = re.compile(r"\b([A-Z]\w+)\s+struct\b")


def declared(src: str, name: str, kind: str) -> bool:
    return bool(re.search(rf"^type {re.escape(name)} {kind}\b", src, re.M))


def check_tree(purposes: list[str], sources: dict[str, str]) -> list[tuple[str, str]]:
    """[(name, file)] for each spec-named struct the tree declares as an interface instead."""
    wanted = {m.group(1) for p in purposes for m in STRUCT_IN_PROSE.finditer(p or "")}
    out = []
    for name in sorted(wanted):
        as_struct = any(declared(s, name, "struct") for s in sources.values())
        if as_struct:
            continue
        as_iface = [f for f, s in sources.items() if declared(s, name, "interface")]
        if as_iface:
            out.append((name, as_iface[0]))
    return out


def self_test() -> int:
    fails = []
    P = ["A Foo struct holding two maps, built by NewFoo()."]
    if check_tree(P, {"a.go": "type Foo interface {\n}\n"}) != [("Foo", "a.go")]:
        fails.append("spec says struct, tree says interface -> must flag")
    if check_tree(P, {"a.go": "type Foo struct {\n}\n"}):
        fails.append("a matching struct must be silent")
    if check_tree(P, {"a.go": "type Foo interface{}\n", "b.go": "type Foo struct{}\n"}):
        fails.append("declared as BOTH must be silent — some specs describe an interface and "
                     "a struct of similar name")
    if check_tree(P, {"a.go": "package x\n"}):
        fails.append("a name declared NOWHERE is absence, not a shape defect, and the compiler "
                     "already catches it")
    # A struct under a DIFFERENT name is the symbol-placement question, declined as unreliable.
    if check_tree(P, {"a.go": "type FooImpl struct{}\n"}):
        fails.append("a differently-named struct must not be flagged here")
    # Prose that merely mentions the word must not create a target.
    if check_tree(["the struct is guarded by a mutex"], {"a.go": "type Foo interface{}\n"}):
        fails.append("lowercase/no-name prose must not produce a target")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — interface-for-struct flagged; matching, both-declared, absent "
                           "and differently-named all silent"))
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    root = pathlib.Path(__file__).resolve().parent
    want = [a for a in argv if not a.startswith("-")]
    rows, checked = [], 0
    for spec in sorted((root / "specs").glob("*.yaml")):
        if spec.name.startswith("_"):
            continue
        try:
            s = yaml.safe_load(spec.read_text())
        except Exception:
            continue
        name = s.get("name")
        if not name or (want and name not in want):
            continue
        purposes = [f.get("purpose", "") for f in s.get("files", [])]
        checked += len({m.group(1) for p in purposes for m in STRUCT_IN_PROSE.finditer(p or "")})
        for gen in ("v4", "v5"):
            tree = root / "generated" / f"{name}-{gen}"
            if not tree.is_dir():
                continue
            srcs = {str(p.relative_to(tree)): p.read_text(errors="ignore")
                    for p in tree.rglob("*.go")}
            for sym, where in check_tree(purposes, srcs):
                rows.append((f"{name}-{gen}", sym, where))
    seen, uniq = set(), []
    for r in rows:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    print(f"checked {checked} spec-named struct(s)")
    if not uniq:
        print("  every one is declared as a struct, or as both, or not at all")
        return 0
    print(f"  {len(uniq)} declared as an INTERFACE instead:\n")
    for tree, sym, where in uniq:
        print(f"    {tree:<22} spec says '{sym} struct' -> type {sym} interface  ({where})")
    print("\n  A green suite tests behaviour, not the shape of the type it went through. Nothing")
    print("  else in this repo asks this question.")
    return 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    if [a for a in sys.argv[1:] if a.startswith("-")]:
        raise SystemExit("REFUSING: takes --self-test or a list of spec names.")
    raise SystemExit(main(sys.argv[1:]))
