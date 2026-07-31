#!/usr/bin/env python3
"""Split a builder log into BUILDS. One definition, because a log file is not a build.

    from _logseg import builds_of, build_count, assert_single_build

    ./_logseg.py                # census: which logs hold more than one build
    ./_logseg.py --self-test

WHY THIS IS SHARED. On 31 July two instruments in this repo disagreed about how many builds the
archive holds — 651/654 against 853 — because they segmented differently and neither segmenter had
been measured. The smaller number was the denominator of several published rates. A second copy of
this logic is how that happens again.

TERMINATOR-BASED, NOT START-BASED. The obvious split is the build's opening line,
`generate <file> (1/N)`. Measured: 103 log files record builds that run to completion and never
print it, holding 160 builds that are INVISIBLE to a start-based segmenter — absent, not
miscounted. A build ends unambiguously in both outcomes:

    success   "Generated <name> into <path>"      a failed build prints this ZERO times
                                                  (checked on ledger-parity-arm-1 and
                                                   ledger-stampfix-arm-4)
    failure   "exhausted N fix rounds"

⚠️ WHAT THIS STILL CANNOT DO. A build killed mid-flight prints neither terminator, so it lands in
the trailing segment together with anything else after the last outcome — a suite's RESULT summary,
for instance. Those segments are labelled INDETERMINATE by callers and must not be counted as
builds; 35 logs in the archive have a start and no outcome.
"""
from __future__ import annotations

import pathlib
import re
import sys

BUILD_END = re.compile(r"^Generated \S+ into |exhausted \d+ fix rounds")
BUILD_OK = re.compile(r"^Generated \S+ into ", re.M)
BUILD_FAIL = re.compile(r"exhausted \d+ fix rounds")


def builds_of(text: str) -> list[str]:
    """Per-build segments. A trailing segment with no terminator is kept — it may be a build
    still in flight, and dropping it would silently lose the only in-progress case."""
    segs, cur = [], []
    for line in text.splitlines(keepends=True):
        cur.append(line)
        if BUILD_END.search(line):
            segs.append("".join(cur))
            cur = []
    if cur and "".join(cur).strip():
        segs.append("".join(cur))
    return segs or [text]


def build_count(text: str) -> int:
    """COMPLETED builds only — segments carrying an outcome marker. Not len(builds_of())."""
    return len(BUILD_OK.findall(text)) + len(BUILD_FAIL.findall(text))


def assert_single_build(text: str, name: str = "this log") -> None:
    """Refuse rather than silently misread. For tools that grade ONE draw and would otherwise
    report whichever build's marker their regex happened to hit first."""
    n = build_count(text)
    if n > 1:
        raise SystemExit(
            f"REFUSING: {name} holds {n} completed builds, and this tool grades one.\n"
            f"  Whole-text matching would report whichever build's marker matched first.\n"
            f"  53 logs in this archive are multi-build (sweep-v5-07290011 holds 23)."
        )


def census(paths: list[pathlib.Path]) -> int:
    multi = []
    total = 0
    for p in paths:
        try:
            t = p.read_text(errors="replace")
        except OSError:
            continue
        n = build_count(t)
        total += n
        if n > 1:
            multi.append((p.name, n))
    print(f"  log files                       {len(paths)}")
    print(f"  completed builds                {total}")
    print(f"  files holding more than one     {len(multi)}")
    print(f"  builds inside those files       {sum(n for _, n in multi)}")
    print("\n  largest:")
    for n, c in sorted(multi, key=lambda x: -x[1])[:8]:
        print(f"    {n:46s} {c:3d}")
    return 0


def self_test() -> int:
    ok = True

    def chk(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: {got!r} != {want!r}")

    green = ("[guildlm-build] compile/test FAILED, fix round 1\n"
             "[guildlm-build] converged to green after fix round 1\n"
             "Generated shortener into ./generated/x\n")
    red = ("[guildlm-build] compile/test FAILED, fix round 1\n"
           "[guildlm-build] exhausted 6 fix rounds (5 budgeted), still failing\n")

    chk("one green build", len(builds_of(green)), 1)
    chk("one failed build", len(builds_of(red)), 1)
    chk("two builds split", len(builds_of(green + green)), 2)
    chk("mixed outcomes split", len(builds_of(red + green)), 2)
    # ⚠️ THE CASE A START-BASED SEGMENTER MISSES: no "(1/N)" line anywhere above.
    chk("split with no (1/N) line", len(builds_of(green * 4)), 4)
    chk("in-flight trailing segment kept",
        len(builds_of(green + "[guildlm-build] compile/test FAILED, fix round 1\n")), 2)

    chk("count is outcomes, not segments", build_count(green + "trailing junk\n"), 1)
    chk("count sums both outcomes", build_count(red + green), 2)
    chk("a non-build log counts zero", build_count("hello\nworld\n"), 0)
    # a failed build must not be mistaken for a success
    chk("failure does not print the success marker", bool(BUILD_OK.search(red)), False)

    try:
        assert_single_build(green + green, "x.log")
        ok = False
        print("  FAIL assert_single_build did not refuse a 2-build log")
    except SystemExit:
        pass
    try:
        assert_single_build(green, "x.log")
    except SystemExit:
        ok = False
        print("  FAIL assert_single_build refused a single-build log")

    print("  self-test: OK — terminator split, outcomes counted, multi-build refused"
          if ok else "  self-test: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(census(sorted((pathlib.Path(__file__).parent / "logs").glob("*.log"))))
