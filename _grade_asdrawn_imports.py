#!/usr/bin/env python3
"""Did the MODEL write the unprefixed import path? Read it from the pre-repair snapshot.

    python _grade_asdrawn_imports.py generated/taskapipro-preedit
    python _grade_asdrawn_imports.py --self-test

WHY THIS EXISTS, AND WHY IT COULD NOT EXIST BEFORE 18:17 TODAY
The import question — "did this draw write `taskapipro/internal/models` instead of
`guildlm.dev/taskapipro/internal/models`?" — was answered all afternoon from ROUND-1 COMPILER
OUTPUT, and that has a hole. Go builds per package and skips any whose dependency failed, so
when chain5's round 1 died in internal/store, internal/api was never built and its imports
were never evaluated. Zero errors, and zero information. That cost the twelve-line finding one
of its two control arms at 17:26.

    A source-level read has no such hole. The import path is either in the file or it is not,
    whether or not a compiler ever looked at the file.

    What made it impossible earlier is that the tree on disk is POST-REPAIR: the deterministic
    pass fixes import paths, so by the time anyone can read a tree, the answer is gone. All
    four taskapipro trees show correct imports today; two of them demonstrably did not when
    they were drawn.

`<out>/.pre-fix.json` closes that. It is the `written` dict at the head of _fix_loop — every
file exactly as the model produced it, before the first check. This reads the import block out
of it and reports what was actually written.

VERDICTS
    CORRECT     every internal/api import of a first-party package carries the module prefix
    UNPREFIXED  at least one does not — the defect, measured at the source
    NO-SNAPSHOT  the draw predates .pre-fix.json. Says nothing; do not score it.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

# `"guildlm.dev/taskapipro/internal/models"` or the broken `"taskapipro/internal/models"`
IMPORT = re.compile(r'"([A-Za-z0-9_.\-/]+/internal/[a-z]+)"')


def grade(tree: pathlib.Path, pkg: str = "internal/api", module: str | None = None) -> dict:
    snap = tree / ".pre-fix.json"
    if not snap.is_file():
        return {"verdict": "NO-SNAPSHOT",
                "why": f"{snap} does not exist — this draw predates the pre-repair snapshot, "
                       f"so what the model wrote is not recoverable"}
    written = json.loads(snap.read_text())
    if module is None:
        gomod = written.get("go.mod", "")
        m = re.search(r"^module\s+(\S+)", gomod, re.M)
        module = m.group(1) if m else ""
    if not module:
        return {"verdict": "NO-SNAPSHOT", "why": "no module path in the snapshot's go.mod"}

    good, bad = [], []
    for path, src in sorted(written.items()):
        if not path.startswith(pkg) or not path.endswith(".go"):
            continue
        for imp in IMPORT.findall(src):
            if imp.startswith(module + "/"):
                good.append((path, imp))
            else:
                bad.append((path, imp))
    if not good and not bad:
        return {"verdict": "NO-SNAPSHOT",
                "why": f"no first-party imports found under {pkg} in the snapshot"}
    return {"verdict": "UNPREFIXED" if bad else "CORRECT", "module": module,
            "good": good, "bad": bad,
            "why": (f"{len(bad)} import(s) under {pkg} lack the module prefix"
                    if bad else
                    f"all {len(good)} first-party import(s) under {pkg} carry `{module}/`")}


def self_test() -> int:
    import tempfile
    fails = []

    def plant(files):
        d = pathlib.Path(tempfile.mkdtemp())
        (d / ".pre-fix.json").write_text(json.dumps(files))
        return d

    mod = "module guildlm.dev/taskapipro\n\ngo 1.23\n"
    ok = plant({"go.mod": mod,
                "internal/api/projects.go":
                    'package api\n\nimport (\n\t"guildlm.dev/taskapipro/internal/models"\n)\n'})
    if grade(ok)["verdict"] != "CORRECT":
        fails.append("a prefixed import must grade CORRECT")

    broken = plant({"go.mod": mod,
                    "internal/api/projects.go":
                        'package api\n\nimport (\n\t"taskapipro/internal/models"\n)\n'})
    g = grade(broken)
    if g["verdict"] != "UNPREFIXED" or len(g["bad"]) != 1:
        fails.append(f"the unprefixed path is the DEFECT and must be named; got {g}")

    # A file OUTSIDE the package must not be scored — internal/service was always correct
    # even in the broken draws, and counting it would mask the defect.
    outside = plant({"go.mod": mod,
                     "internal/service/service.go":
                         'package service\n\nimport (\n\t"taskapipro/internal/models"\n)\n',
                     "internal/api/projects.go":
                         'package api\n\nimport (\n\t"guildlm.dev/taskapipro/internal/models"\n)\n'})
    if grade(outside)["verdict"] != "CORRECT":
        fails.append("only the named package is scored — a defect elsewhere is a different "
                     "question and must not flip this verdict")

    # STDLIB IMPORTS MUST NOT COUNT. They have no module prefix and never should.
    std = plant({"go.mod": mod,
                 "internal/api/projects.go":
                     'package api\n\nimport (\n\t"net/http"\n\t"encoding/json"\n'
                     '\t"guildlm.dev/taskapipro/internal/models"\n)\n'})
    if grade(std)["verdict"] != "CORRECT":
        fails.append("net/http has no module prefix and must not read as the defect — the "
                     "pattern requires /internal/ precisely to avoid this")

    if grade(pathlib.Path(tempfile.mkdtemp()))["verdict"] != "NO-SNAPSHOT":
        fails.append("a tree with no snapshot must say so, not report CORRECT")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — prefixed/unprefixed separated, stdlib ignored, other packages "
                           "out of scope, and a missing snapshot is not a pass"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    pkg = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--pkg=")), "internal/api")
    bad_flags = [a for a in sys.argv[1:] if a.startswith("-") and not a.startswith("--pkg=")]
    if bad_flags:
        raise SystemExit(f"REFUSING: unknown flag(s) {' '.join(bad_flags)}.")
    if not args:
        raise SystemExit(__doc__)
    rc = 0
    for a in args:
        g = grade(pathlib.Path(a), pkg=pkg)
        mark = {"CORRECT": "✓", "UNPREFIXED": "✗", "NO-SNAPSHOT": "—"}[g["verdict"]]
        print(f"{mark} {a}  {g['verdict']}")
        print(f"    {g['why']}")
        for p, i in g.get("bad", []):
            print(f"    DEFECT  {p}: \"{i}\"")
        if g["verdict"] == "NO-SNAPSHOT":
            rc = 1
    raise SystemExit(rc)
