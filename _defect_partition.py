#!/usr/bin/env python3
"""Which compiler/vet defects appear in EVERY +12-line draw and in NO draw without them?

    python _defect_partition.py
    python _defect_partition.py --self-test

WHY. `undefined: w` at projects_test.go:183:2 was spotted by eye in a running log, and it
turned out to partition the five taskapipro draws exactly by whether twelve lines had been
added to the projects entry — with the server controlled by chain5 and the content controlled
by the inert arm. Finding one such defect by reading a log is luck. This asks the same
question of every defect in every round at once.

THE PARTITION
    CONTROL    chain4  (PRE-edit, no added lines, other server, 28 Jul)
               chain5  (PRE-edit, no added lines, server 4439, 29 Jul)
    TREATMENT  v5 x2   (+12 REAL lines,  server 4439)
               inert   (+12 INERT lines, server 4439)

A defect in ALL treatment draws and NO control draw is a candidate for "the twelve lines cause
it, whatever they say" — because the treatment arms disagree on the prose and the controls
include one on the same server.

⚠️ THE BIAS THIS TOOL MUST NOT HIDE, and it is why round depth is printed on every run.
The draws did not run the same number of rounds: chain4 CONVERGED after round 1, so it had one
chance to exhibit anything, while the treatment arms ran six or seven. A defect "absent from
chain4" may simply be absent from chain4's single round. chain5 is the load-bearing control
precisely because it went the distance — 7 rounds — and it is the one on the same server.

    So the tool reports two columns: whether a defect is absent from ALL controls, and
    whether it is absent from chain5 SPECIFICALLY. The second is the honest one.

NORMALISATION. Line and column numbers are KEPT — the sharpest signal in the original find was
that the line matched to the column across draws with different prose. Only addresses,
goroutine ids and timings are blanked, matching the builder's own _error_signature.
"""
from __future__ import annotations

import collections
import pathlib
import re
import sys

LOGS = pathlib.Path(__file__).resolve().parent / "logs"

CONTROL = {
    "chain4": "taskapipro-chain-07282227.log",
    "chain5": "taskapipro-chain-07291509.log",
}
TREATMENT = {
    "v5-1st": "ab-taskapipro-v5-07290930.log",
    "v5-2nd": "ab-taskapipro-v5-07291327.log",
    "inert": "inert-taskapipro-07291641.log",
}

NOISE = re.compile(r"0x[0-9a-f]+|goroutine \d+|\d+\.\d+s|\+0x[0-9a-f]+")
# `[guildlm-build]     ! <something>` — the builder's filtered error view.
ERRLINE = re.compile(r"^\[guildlm-build\]\s+!\s+(.*?)\s*$", re.M)
# Structural lines that are not defects: package headers, no-test-files, ok lines, FAIL summaries.
SKIP = re.compile(r"^(#|\?|ok\s|FAIL\s|---\s|vet:\s*$|\[build failed\]|\[setup failed\])")


ROUND_HDR = re.compile(r"compile/test FAILED, fix round (\d+)/")


def defects_by_round(text: str) -> dict[str, int]:
    """Each normalised defect -> the FIRST round it appeared in.

    THE DIMENSION THIS TOOL SHIPPED WITHOUT, and it nearly cost a published result its
    meaning. A defect seen in ROUND 1 is AS-DRAWN: it describes what the model wrote. A
    defect first seen in round 2 or later has survived a round of repair — 4 or 5 fixes were
    applied to projects_test.go in round 1 of every taskapipro draw — so "present in
    treatment, absent in control" at round 2 compares post-repair states, not draws.

    Both are real findings and they are not the same finding. Round 1 says the SPEC produced
    it; round 2+ says the spec produced a tree whose repair leaves it in place. Printing the
    round is the difference between those two sentences.
    """
    out: dict[str, int] = {}
    rnd = 0
    for ln in text.splitlines():
        m = ROUND_HDR.search(ln)
        if m:
            rnd = int(m.group(1))
            continue
        em = ERRLINE.match(ln)
        if not em:
            continue
        line = NOISE.sub("?", em.group(1)).strip()
        if not line or SKIP.match(line):
            continue
        line = re.sub(r"\s*\(/[^)]*\)$", "", line)
        if line not in out:
            out[line] = rnd
    return out


def defects(text: str) -> set[str]:
    """Distinct normalised error lines across every round of one log."""
    out = set()
    for raw in ERRLINE.findall(text):
        line = NOISE.sub("?", raw).strip()
        if not line or SKIP.match(line):
            continue
        # Drop the parenthesised GOROOT path Go appends to "is not in std" — it is machine
        # state, not a property of the draw, and it would make otherwise-identical defects
        # differ across toolchain versions.
        line = re.sub(r"\s*\(/[^)]*\)$", "", line)
        out.add(line)
    return out


def rounds(text: str) -> int:
    return len(re.findall(r"compile/test FAILED, fix round \d+/", text))


def self_test() -> int:
    fails = []
    log = (
        "[guildlm-build] compile/test FAILED, fix round 1/6\n"
        "[guildlm-build]     ! # guildlm.dev/x/internal/api\n"
        "[guildlm-build]     ! internal/api/p.go:7:2: package x/internal/models is not in std (/opt/go/src/x)\n"
        "[guildlm-build]     ! ?   \tguildlm.dev/x/cmd/server\t[no test files]\n"
        "[guildlm-build]     ! ok  \tguildlm.dev/x/internal/store\t0.413s\n"
        "[guildlm-build] compile/test FAILED, fix round 2/6\n"
        "[guildlm-build]     ! vet: internal/api/p_test.go:183:2: undefined: w\n"
    )
    d = defects(log)
    if "internal/api/p.go:7:2: package x/internal/models is not in std" not in d:
        fails.append(f"the GOROOT path must be stripped but the file:line:col kept; got {d}")
    if any(x.startswith("#") or x.startswith("?") or x.startswith("ok") for x in d):
        fails.append("package headers, no-test-files and ok lines are not defects")
    if "vet: internal/api/p_test.go:183:2: undefined: w" not in d:
        fails.append("a vet error is a defect and its line:col must survive")
    if len(d) != 2:
        fails.append(f"exactly 2 defects in that fixture, got {len(d)}: {d}")
    if rounds(log) != 2:
        fails.append(f"two round headers, got {rounds(log)}")
    # Line numbers must NOT be normalised away — that was the sharpest signal in the find.
    a = defects("[guildlm-build]     ! vet: p_test.go:183:2: undefined: w\n")
    b = defects("[guildlm-build]     ! vet: p_test.go:184:2: undefined: w\n")
    if a == b:
        fails.append("different LINES must stay different — a line-and-column match across "
                     "draws is the whole reason this is worth measuring")
    # But timings must be, or two identical runs would look different.
    if defects("[guildlm-build]     ! ok x 0.413s\n") != defects("[guildlm-build]     ! ok x 0.303s\n"):
        fails.append("timings must normalise")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — GOROOT stripped, line:col kept, structural lines dropped"))
    return 1 if fails else 0


def main() -> int:
    got = {}
    for label, name in {**CONTROL, **TREATMENT}.items():
        p = LOGS / name
        if not p.is_file():
            print(f"  missing: {name}")
            continue
        text = p.read_text(errors="ignore")
        got[label] = (defects(text), rounds(text))

    print("DRAWS")
    for label in list(CONTROL) + list(TREATMENT):
        if label not in got:
            continue
        arm = "CONTROL  " if label in CONTROL else "TREATMENT"
        d, r = got[label]
        print(f"   {arm} {label:<8} {r} round(s)   {len(d)} distinct defect(s)")
    ctrl = [l for l in CONTROL if l in got]
    treat = [l for l in TREATMENT if l in got]
    if not ctrl or not treat:
        print("\n   need at least one arm on each side")
        return 2

    in_all_treat = set.intersection(*(got[l][0] for l in treat))
    in_any_ctrl = set.union(*(got[l][0] for l in ctrl))
    only_treat = sorted(in_all_treat - in_any_ctrl)

    print(f"\nDEFECTS IN EVERY TREATMENT DRAW AND NO CONTROL DRAW  ({len(only_treat)})")
    by_round = {}
    for label, name in {**CONTROL, **TREATMENT}.items():
        p = LOGS / name
        if p.is_file():
            by_round[label] = defects_by_round(p.read_text(errors="ignore"))
    for d in only_treat:
        c5 = "absent from chain5 too" if "chain5" in got and d not in got["chain5"][0] else \
             "⚠ present in chain5"
        first = {l: by_round[l][d] for l in treat if l in by_round and d in by_round[l]}
        stage = ("AS-DRAWN (round 1 in every treatment arm)"
                 if first and set(first.values()) == {1}
                 else f"POST-REPAIR — first seen in round(s) {sorted(set(first.values()))}, "
                      f"after that file had already been fixed")
        print(f"   {d}")
        print(f"       {c5}")
        print(f"       {stage}")
    if not only_treat:
        print("   none")

    # The reverse direction is a real question too: something the CONTROLS all have and no
    # treatment draw does would mean the twelve lines SUPPRESS a defect.
    in_all_ctrl = set.intersection(*(got[l][0] for l in ctrl))
    in_any_treat = set.union(*(got[l][0] for l in treat))
    only_ctrl = sorted(in_all_ctrl - in_any_treat)
    print(f"\nDEFECTS IN EVERY CONTROL DRAW AND NO TREATMENT DRAW  ({len(only_ctrl)})")
    for d in only_ctrl:
        print(f"   {d}")
    if not only_ctrl:
        print("   none")

    print("\n⚠️ ROUND DEPTH IS NOT EQUAL, so 'absent from a control' is weaker than it looks:")
    print("   chain4 converged after round 1 and had ONE chance to exhibit anything.")
    print("   chain5 is the load-bearing control — it ran the distance AND it is the only")
    print("   control on server 4439, so it holds the server fixed against the treatment arms.")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    if [a for a in sys.argv[1:] if a.startswith("-")]:
        raise SystemExit("REFUSING: takes --self-test or nothing.")
    raise SystemExit(main())
