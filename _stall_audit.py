#!/usr/bin/env python3
"""Which fix loops stalled — the same failure repeating until the budget ran out?

    python _stall_audit.py logs/ab-*-v5-0729*.log
    python _stall_audit.py --self-test

THE SIGNAL. If round N and round N+1 report the same failure, the loop has stopped making
progress and the remaining rounds cannot recover it. Measured on the v5 corpus: two specs
stalled (taskapi from round 2, expreval from round 1), both spent every remaining round,
both shipped NOT-GREEN. Seven rounds of best-of-N calls that could not have helped. Nothing
in the loop compares this round's failure to the last one, so it is spent in full every
time.

This is the read-only half of that. The abort itself belongs in src/ and waits for the
draws to drain; this tool answers "how often does it happen" on logs already written, which
is the question that decides whether the abort is worth building.

⚠️ PASS THE DATESTAMP, NOT JUST THE SPEC NAME. logs/ab-workapi-v5-07081249.log is from 8
July and matches `ab-workapi-v5-*.log` exactly as today's draw will. That stale file put a
spurious "workapi, 5 rounds" row into the first count this tool was written to replace. The
glob is the caller's job and getting it wrong is silent, so the report prints the file's
date beside every row.

WHAT COUNTS AS "THE SAME FAILURE". The compared signature is the set of `!`-prefixed lines
in a round, minus the ones that are noise in every round ("[no test files]", bare package
headers). Comparing raw text would call two rounds different because a line moved; comparing
only the first line would call them the same because both start with a package header. The
self-test plants both.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROUND = re.compile(r"compile/test FAILED, fix round (\d+)/(\d+)")
ERRLINE = re.compile(r"^\[guildlm-build\]     ! (.*)$")
# Lines that appear in every round regardless of what is wrong. Keeping them would make two
# genuinely different rounds look similar; dropping them is what makes the comparison about
# the FAILURE rather than about the report's framing.
NOISE = re.compile(r"^\?\s|\[no test files\]|^#\s|^# \[")


def rounds(path: pathlib.Path) -> list[tuple[int, int, frozenset[str]]]:
    """(round_number, budget, signature) per fix round, in order."""
    out: list[tuple[int, int, frozenset[str]]] = []
    cur: list[str] | None = None
    n = budget = 0
    for line in path.read_text(errors="replace").splitlines():
        m = ROUND.search(line)
        if m:
            if cur is not None:
                out.append((n, budget, frozenset(cur)))
            n, budget, cur = int(m.group(1)), int(m.group(2)), []
            continue
        if cur is not None:
            e = ERRLINE.match(line)
            if e and not NOISE.match(e.group(1).strip()):
                cur.append(e.group(1).strip())
    if cur is not None:
        out.append((n, budget, frozenset(cur)))
    return out


def stall_from(rs: list[tuple[int, int, frozenset[str]]]) -> int | None:
    """First round whose signature repeats ANY earlier round's, or None.

    SET MEMBERSHIP, NOT CONSECUTIVE COMPARISON — and the first version of this got it wrong.
    The builder's own check is `if sig in seen_surfaces`, a set over every round so far, and
    it is right: an error that comes back after two rounds of something else is as dead as
    one that repeats immediately, because the loop has demonstrably been in that state and
    left it without fixing it.

    Caught live on taskapipro-v5, which this tool called "progress":

        round 2   vet: internal/api/projects_test.go:183:2: undefined: w
        round 3   too many arguments in call to h.svc.List
        round 4   declared and not used: status
        round 5   vet: internal/api/projects_test.go:183:2: undefined: w   <- round 2, again

    Consecutive comparison sees rounds 3 and 4 in between and reports progress. The run had
    in fact returned to a state it had already failed to leave. Comparing only to the
    previous round answers "did the last fix change anything", which is a different and much
    weaker question than "has this loop been here before".
    """
    seen: set[frozenset[str]] = set()
    for n, _budget, sig in rs:
        if sig and sig in seen:
            return n
        if sig:
            seen.add(sig)
    return None


def self_test() -> int:
    import tempfile
    fails = []

    def log(text: str) -> pathlib.Path:
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as fh:
            fh.write(text)
            return pathlib.Path(fh.name)

    R = "[guildlm-build] compile/test FAILED, fix round {}/5\n"
    E = "[guildlm-build]     ! {}\n"
    # A stall: identical failures in rounds 2 and 3.
    p = log(R.format(1) + E.format("boom A")
            + R.format(2) + E.format("boom B")
            + R.format(3) + E.format("boom B"))
    if stall_from(rounds(p)) != 3:
        fails.append(f"a repeated failure must be flagged at round 3, got {stall_from(rounds(p))}")
    # Progress: a different failure each round is NOT a stall.
    p2 = log(R.format(1) + E.format("boom A") + R.format(2) + E.format("boom B"))
    if stall_from(rounds(p2)) is not None:
        fails.append("different failures each round must not be flagged as a stall")
    # NON-CONSECUTIVE RECURRENCE — the case the first version of this tool missed, taken
    # verbatim from taskapipro-v5: round 2's failure returns at round 5 with two different
    # failures in between, and the tool called the whole run "progress".
    p2b = log(R.format(1) + E.format("boom A")
              + R.format(2) + E.format("undefined: w")
              + R.format(3) + E.format("too many arguments")
              + R.format(4) + E.format("declared and not used")
              + R.format(5) + E.format("undefined: w"))
    if stall_from(rounds(p2b)) != 5:
        fails.append(f"a failure returning after two other rounds is a stall at round 5, "
                     f"got {stall_from(rounds(p2b))}")
    # ORDER MUST NOT MATTER. Same two errors, swapped, is the same failure.
    p3 = log(R.format(1) + E.format("x") + E.format("y")
             + R.format(2) + E.format("y") + E.format("x"))
    if stall_from(rounds(p3)) != 2:
        fails.append("two rounds with the same errors in a different order are a stall")
    # NOISE MUST NOT CREATE A MATCH. Rounds differing only in real errors, sharing noise.
    p4 = log(R.format(1) + E.format("?   pkg/x [no test files]") + E.format("real A")
             + R.format(2) + E.format("?   pkg/x [no test files]") + E.format("real B"))
    if stall_from(rounds(p4)) is not None:
        fails.append("shared noise lines must not make two different rounds look identical")
    # ...and noise alone must not count as a signature at all.
    p5 = log(R.format(1) + E.format("?   pkg/x [no test files]")
             + R.format(2) + E.format("?   pkg/x [no test files]"))
    if stall_from(rounds(p5)) is not None:
        fails.append("two rounds whose only shared lines are noise are not a measured stall")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — repeats flagged, progress spared, order-insensitive, "
                           "and noise neither matches nor counts"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    paths = [pathlib.Path(a) for a in sys.argv[1:] if not a.startswith("-")]
    if not paths:
        raise SystemExit(__doc__)
    import datetime
    wasted = total = 0
    print(f"{'log':<38} {'date':<11} {'rounds':>6}  verdict")
    for p in sorted(paths):
        rs = rounds(p)
        if not rs:
            continue
        total += 1
        d = datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%m-%d %H:%M")
        s = stall_from(rs)
        last, budget = rs[-1][0], rs[-1][1]
        if s is None:
            v = "progress"
        else:
            w = last - s + 1
            wasted += w
            v = f"STALLED from round {s} — {w} round(s) spent on a failure that never moved"
        print(f"{p.name:<38} {d:<11} {last:>3}/{budget}  {v}")
    print(f"\n{wasted} wasted round(s) across {total} log(s) with at least one fix round.")
