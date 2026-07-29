#!/usr/bin/env python3
"""Did this draw have the unprefixed-import defect — and if the count is 0, was it MEASURED?

    python _grade_import_defect.py logs/ab-taskapipro-v5-07290930.log
    python _grade_import_defect.py --pkg=internal/store logs/taskapipro-chain-07291509.log
    python _grade_import_defect.py --self-test

Exits 1 if ANY arm is UNMEASURED, so a masked draw cannot be scored by accident in a pipeline.

WHY A SEPARATE TOOL, AND WHY THE SECOND QUESTION EXISTS
The four-draw table behind "the twelve-line spec edit caused the import defect" counts
import-path errors in ROUND 1, because round-1 output is the only measurement taken before
any repair. Two arms read 0 and two read 4, and the 0s were treated as equivalent evidence.

They are not. Go reports errors per PACKAGE and stops building a package whose dependency
failed. If internal/store fails to compile, internal/api is never built, its imports are never
resolved, and a broken import there produces NO OUTPUT AT ALL.

    chain4  round 1: `# guildlm.dev/taskapipro/internal/api`, then `undefined:
            service.ErrNotFound` — a TYPE error inside internal/api. You cannot reach an
            undefined-symbol error in package `service` unless the import of `service`
            RESOLVED. So internal/api compiled far enough to prove its imports were fine.
            0 import errors, MEASURED.

    chain5  round 1: `# guildlm.dev/taskapipro/internal/store`, `undefined: Task`. The string
            "internal/api" does not appear anywhere in that round. internal/api was never
            reached, so its imports were never evaluated.
            0 import errors, NOT MEASURED. Unusable as a control.

That distinction is invisible in a count, and counting is what the table did.

THE DECISION PROCEDURE
    no round 1 at all              the whole tree compiled -> imports are FINE, measured
    >=1 import-path error          the defect is PRESENT, measured
    0 errors, internal/api present the package was compiled and said nothing about imports
                                   -> imports FINE, measured
    0 errors, internal/api absent  -> UNMEASURED. Do not score this arm.

WHY IT IS NOT PART OF _inert_prose_draw.sh: that script is RUNNING. bash re-reads a script
from a byte offset as it executes, so editing a live one can splice a half-line into the
middle of a command. This repo has that hazard written down; a separate tool costs nothing
and the grader is reusable across every arm rather than living inside one runner.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROUND1 = re.compile(r"compile/test FAILED, fix round 1/")
ROUND2 = re.compile(r"compile/test FAILED, fix round 2/")
# The fix actions end the error block; anything after them is repair, not measurement.
END = re.compile(r"^\[guildlm-build\]\s+(deterministic fix|fixing |rebuilt a request|"
                 r"widening fix targets|error surface)")
IMPORT_ERR = re.compile(r"is not in std|could not import")
# THE PACKAGE WHOSE IMPORTS ARE THE SUBJECT. Hardcoding taskapipro's layout into a tool that
# prints general-sounding verdicts is how a future run gets a confident answer about the wrong
# package: for an artifact with no internal/api, EVERY zero would read as UNMEASURED.
# Overridable, and the verdict text names the package it actually checked.
PKG = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--pkg=")), "internal/api")


def round1_block(text: str) -> list[str] | None:
    """The error lines of round 1, or None if the draw never had a round 1."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ROUND1.search(ln)), None)
    if start is None:
        return None
    out = []
    for ln in lines[start + 1:]:
        if ROUND2.search(ln) or END.match(ln):
            break
        out.append(ln)
    return out


def grade(text: str) -> dict:
    block = round1_block(text)
    if block is None:
        return {"verdict": "FINE", "errors": 0, "measured": True,
                "why": "no round 1 — the tree compiled, so imports resolved"}
    errs = [ln for ln in block if IMPORT_ERR.search(ln)]
    if errs:
        files = sorted({m.group(1) for ln in errs
                        for m in [re.search(r"(\S+\.go):\d+:\d+:", ln)] if m})
        return {"verdict": "DEFECT", "errors": len(errs), "measured": True,
                "files": files,
                "why": f"{len(errs)} import-path error line(s) in round 1"}
    if any(PKG in ln for ln in block):
        return {"verdict": "FINE", "errors": 0, "measured": True,
                "why": f"{PKG} appears in round 1 with non-import errors — it compiled "
                       f"far enough to resolve its imports"}
    return {"verdict": "UNMEASURED", "errors": 0, "measured": False,
            "why": f"round 1 failed elsewhere and {PKG} never appears — its imports "
                   f"were never evaluated. This arm cannot be scored."}


def self_test() -> int:
    fails = []
    conv = "[guildlm-build] generate a.go (1/2)\n[guildlm-build] compile/test passed\n"
    if grade(conv)["verdict"] != "FINE":
        fails.append("a draw with no round 1 compiled, so its imports are fine")

    defect = ("[guildlm-build] compile/test FAILED, fix round 1/6\n"
              "[guildlm-build]     ! internal/api/projects.go:7:2: package "
              "taskapipro/internal/models is not in std (/x)\n"
              "[guildlm-build]   deterministic fix in internal/api/projects.go\n")
    g = grade(defect)
    if g["verdict"] != "DEFECT" or g["errors"] != 1 or g["files"] != ["internal/api/projects.go"]:
        fails.append(f"an import error must be DEFECT with its file, got {g}")

    # chain4's shape: internal/api present, TYPE errors, no import errors -> measured FINE.
    typed = ("[guildlm-build] compile/test FAILED, fix round 1/6\n"
             "[guildlm-build]     ! # guildlm.dev/taskapipro/internal/api\n"
             "[guildlm-build]     ! internal/api/projects.go:34:36: undefined: service.ErrExists\n"
             "[guildlm-build]   deterministic fix in internal/api/projects.go\n")
    if grade(typed)["verdict"] != "FINE":
        fails.append("internal/api type-checking proves its imports resolved — that is chain4")

    # chain5's shape: a DIFFERENT package failed, internal/api absent -> UNMEASURED.
    masked = ("[guildlm-build] compile/test FAILED, fix round 1/6\n"
              "[guildlm-build]     ! # guildlm.dev/taskapipro/internal/store\n"
              "[guildlm-build]     ! internal/store/store.go:16:36: undefined: Task\n"
              "[guildlm-build]   deterministic fix in internal/store/store.go\n")
    g = grade(masked)
    if g["verdict"] != "UNMEASURED" or g["measured"]:
        fails.append(f"a masked arm must be UNMEASURED, not a 0 — that is chain5. got {g}")

    # THE ONE THAT MATTERS MOST: masked and DEFECT must not be confusable by count alone.
    if grade(masked)["errors"] != grade(typed)["errors"]:
        fails.append("both read 0 errors — the whole point is that the COUNT cannot separate "
                     "them and the verdict must")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — converged/defect/type-checked/masked separated, and the two "
                           "zero-count arms get different verdicts"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    unknown = [a for a in sys.argv[1:] if a.startswith("-") and not a.startswith("--pkg=")]
    if unknown:
        raise SystemExit(f"REFUSING: unknown flag(s) {' '.join(unknown)}. Takes --self-test, "
                         f"--pkg=<path>, or a list of build logs.")
    if not args:
        raise SystemExit(__doc__)
    rc = 0
    for a in args:
        p = pathlib.Path(a)
        if not p.is_file():
            print(f"  {a}: not a file")
            rc = 2
            continue
        g = grade(p.read_text(errors="ignore"))
        mark = {"DEFECT": "✗", "FINE": "✓", "UNMEASURED": "⚠"}[g["verdict"]]
        print(f"{mark} {p.name:<40} {g['verdict']:<11} errors={g['errors']}")
        print(f"    {g['why']}")
        if g.get("files"):
            print(f"    files named by the compiler: {', '.join(g['files'])}")
        if not g["measured"]:
            rc = 1
    raise SystemExit(rc)
