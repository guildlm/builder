#!/usr/bin/env python3
"""Rebuild the go.mod files my glob deleted, from the import paths that survived.

`rm -f generated/*/[a-z]*` took every top-level file, and go.mod starts with a lowercase
letter. Artifacts with NESTED packages kept their source (rm without -r spared the
directories) but lost the module file, so they no longer build and every teeth verdict
against them reads BASELINE-RED — a corpus that looks intact and answers "void" to
everything. That is the shape of damage the row file cannot see, because BASELINE-RED and
a genuinely broken artifact are the same string.

The module path is recoverable: a multi-package artifact imports itself, so
`guildlm.dev/<name>/internal/...` appears verbatim in the source. Nothing is guessed —
an artifact with no self-import is left alone and reported, because inventing a module
path would produce a tree that builds and is not the tree that was there.

    python _restore_gomod.py             # report what it would do
    python _restore_gomod.py --write     # write the files
    python _restore_gomod.py --self-test # planted fixtures; no corpus needed
"""
from __future__ import annotations

import pathlib
import re
import sys
import tempfile

IMPORT_RE = re.compile(r'"((?:[a-z0-9-]+\.)+[a-z]+/[A-Za-z0-9_.-]+)(?:/[A-Za-z0-9_./-]+)?"')
GO_LINE = "go 1.23\n"


def module_from_sources(art: pathlib.Path) -> str | None:
    """The module path this artifact imports itself by, or None if it never does."""
    counts: dict[str, int] = {}
    for f in art.rglob("*.go"):
        for m in IMPORT_RE.finditer(f.read_text(errors="ignore")):
            path = m.group(1)
            counts[path] = counts.get(path, 0) + 1
    if not counts:
        return None
    # The self-import is the one whose LAST segment matches the artifact's own name once
    # the -v4 / -green2 style suffix is stripped; fall back to the most frequent candidate
    # only when exactly one distinct path was seen (a single-module artifact).
    stem = re.split(r"-(v\d+|green\d+|roll\d+|ct|\d+)$", art.name)[0]
    named = [p for p in counts if p.rsplit("/", 1)[-1].replace("-", "") == stem.replace("-", "")]
    if len(named) == 1:
        return named[0]
    if len(counts) == 1:
        return next(iter(counts))
    return None


def artifacts_missing_gomod(gen: pathlib.Path) -> list[pathlib.Path]:
    return [d for d in sorted(gen.iterdir())
            if d.is_dir() and not (d / "go.mod").exists() and any(d.rglob("*.go"))]


def self_test() -> int:
    fails = []
    with tempfile.TemporaryDirectory() as td:
        gen = pathlib.Path(td)
        # 1. a nested artifact that imports itself -> recoverable
        a = gen / "taskapi-v4" / "internal" / "store"
        a.mkdir(parents=True)
        (a / "memory.go").write_text('package store\n\nimport "guildlm.dev/taskapi/internal/models"\n')
        # 2. an artifact with no self-import -> must be REFUSED, not guessed
        b = gen / "loner-v4"
        b.mkdir(parents=True)
        (b / "main.go").write_text('package main\n\nimport "fmt"\n\nfunc main() { fmt.Println() }\n')
        # 3. an artifact that still has its go.mod -> must not be listed at all
        c = gen / "intact-v4"
        c.mkdir(parents=True)
        (c / "go.mod").write_text("module guildlm.dev/intact\n\ngo 1.23\n")
        (c / "main.go").write_text("package main\n\nfunc main() {}\n")

        missing = artifacts_missing_gomod(gen)
        if [d.name for d in missing] != ["loner-v4", "taskapi-v4"]:
            fails.append(f"wrong missing list: {[d.name for d in missing]}")
        if module_from_sources(gen / "taskapi-v4") != "guildlm.dev/taskapi":
            fails.append(f"self-import not recovered: {module_from_sources(gen / 'taskapi-v4')}")
        if module_from_sources(gen / "loner-v4") is not None:
            fails.append("an artifact with only stdlib imports must be refused, not guessed")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else "ok — recovers what it can prove, refuses the rest"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    # REFUSE AN ARGUMENT THIS TOOL DOES NOT TAKE. It works on generated/ and nothing else,
    # so a path handed to it would otherwise be ignored while the tool reported a confident
    # result about a corpus the caller never named — the failure mode
    # tests/test_instruments_reject_nothing.py exists for.
    stray = [a for a in sys.argv[1:] if a not in ("--write", "--self-test")]
    if stray:
        raise SystemExit(f"unexpected argument(s): {' '.join(stray)}\n"
                         f"this tool takes no target — it repairs ./generated only.\n"
                         f"usage: _restore_gomod.py [--write | --self-test]")
    GEN = pathlib.Path(__file__).resolve().parent / "generated"
    if not GEN.is_dir():
        raise SystemExit(f"{GEN} is not a directory")
    write = "--write" in sys.argv
    missing = artifacts_missing_gomod(GEN)
    done = refused = 0
    for art in missing:
        mod = module_from_sources(art)
        if mod is None:
            refused += 1
            print(f"  REFUSED  {art.name:<34} no self-import to read the module path from")
            continue
        done += 1
        if write:
            (art / "go.mod").write_text(f"module {mod}\n\n{GO_LINE}")
    verb = "wrote" if write else "would write"
    print(f"\n{len(missing)} artifact(s) with Go files and no go.mod: "
          f"{verb} {done}, refused {refused}")
    if not write and done:
        print("re-run with --write to apply")
