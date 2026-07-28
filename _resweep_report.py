#!/usr/bin/env python3
"""What the repaired walk actually added, and which survivors are the sharp ones.

Run AFTER _resweep_v4.sh finishes. Reads three tracked files:

    logs/hole-hunt-rows-before-walk-fix.tsv   the sweep as it was, five shapes blind to internal/
    logs/hole-hunt-rows.tsv                   the sweep with the walk repaired
    logs/reachability-rows.tsv                which sites the suite never executes

WHAT THE DELTA IS NOT — printed by the tool, because it is the number a reader will reach for
and the wrong conclusion is the natural one. More rows is not the corpus getting worse and it
is not new holes appearing. Nothing changed in the trees: they are frozen. It is the size of
a question five of six mutation shapes were never asked, because they walked glob("*.go")
and every internal/-layout artifact matched nothing.

THE TRIAGE THIS EXISTS FOR. Cross-validated during the run: COLD => SURVIVED holds, and the
converse does not. So the survivors split into two populations needing different work:

    COLD + SURVIVED   pre-answered — no assertion could catch it. The open question is
                      REACHABILITY through the shipped composition: dead branch, or a real
                      hole nothing requests.
    WARM + SURVIVED   a test EXECUTES the line and asserts nothing about what it produced.
                      Coverage measures lines RUN, not invariants DEFENDED. No cheap check
                      dismisses any of these.

BOUNDED, NOT EXACT, and the tool says so on every line: sweep rows carry no LINE NUMBER, so a
file with mixed cold and warm sites can only be bounded — if a file+shape has k cold sites and
m survivors, at least m-k WARM ones survived.

    python _resweep_report.py
"""
from __future__ import annotations

import collections
import pathlib
import subprocess
import sys

LOGS = pathlib.Path(__file__).resolve().parent / "logs"


def rows(p: pathlib.Path) -> list[list[str]]:
    return [ln.split("\t") for ln in p.read_text().splitlines() if ln.strip()]


def main() -> int:
    # THE TRAP THIS GUARD EXISTS FOR: _hole_hunt writes its rows ONCE, at the END. Run while
    # the sweep is going and hole-hunt-rows.tsv is still the OLD file — so this would compare
    # the before-file to a copy of itself and report, confidently, that nothing changed.
    # A clean "no change" from a measurement that never happened is the exact failure this
    # whole session has been about.
    if subprocess.run(["pgrep", "-f", r"_hole_hunt\.py"],
                      capture_output=True).returncode == 0:
        print("REFUSING: the sweep is still running. logs/hole-hunt-rows.tsv is written ONCE,\n"
              "at the end, so it currently still holds the PRE-fix rows. Comparing now would\n"
              "diff the before-file against a copy of itself and report 'no change' — a clean\n"
              "answer to a measurement that has not happened.")
        return 2

    before_p, after_p = LOGS / "hole-hunt-rows-before-walk-fix.tsv", LOGS / "hole-hunt-rows.tsv"
    for p in (before_p, after_p, LOGS / "reachability-rows.tsv"):
        if not p.is_file():
            print(f"missing {p}")
            return 2
    before, after = rows(before_p), rows(after_p)
    if before == after:
        print("The two row files are IDENTICAL. Either the sweep did not write, or it was\n"
              "run with a positional argument (a targeted run does not replace the baseline).")
        return 2

    bc = collections.Counter(r[0] for r in before)
    ac = collections.Counter(r[0] for r in after)
    print(f"ROWS  before {len(before)}   after {len(after)}   "
          f"(+{len(after) - len(before)})\n")
    print("PER ARTIFACT — the four internal/-layout trees are the point:")
    for art in sorted(set(bc) | set(ac)):
        b, a = bc.get(art, 0), ac.get(art, 0)
        if b != a:
            print(f"   {art:<26} {b:>4} -> {a:>4}   {'+' + str(a - b) if a > b else str(a - b)}")

    print("\nVERDICTS:")
    bv, av = collections.Counter(r[3] for r in before), collections.Counter(r[3] for r in after)
    for v in sorted(set(bv) | set(av)):
        print(f"   {v:<14} {bv.get(v, 0):>4} -> {av.get(v, 0):>4}")

    # WARM + SURVIVED, bounded per (artifact, file, shape-family).
    cold = collections.Counter()
    for r in rows(LOGS / "reachability-rows.tsv"):
        if len(r) >= 5 and r[4] == "COLD":
            cold[(r[0], r[1])] += 1
    # SURVIVED* is the LABELLED-BENIGN class — a statusRecorder default that a logging
    # middleware records before the handler writes anything, so mutating it changes log output
    # and nothing else. It has cost a code-read twice. Counting it in the "sharp set" would
    # inflate the one number this report exists to make small, which is the over-reporting
    # this session has spent all night finding in other tools.
    benign = sum(1 for r in after if r[3] == "SURVIVED*")
    surv = collections.Counter((r[0], r[1]) for r in after if r[3] == "SURVIVED")
    print("\nWARM + SURVIVED (LOWER BOUND) — a test runs the line and asserts nothing:")
    total = 0
    for key in sorted(surv):
        n = surv[key] - cold.get(key, 0)
        if n > 0:
            total += n
            print(f"   {key[0]:<26} {key[1]:<34} >= {n}")
    print(f"\n   at least {total} site(s) executed and undefended.")
    if benign:
        print(f"   ({benign} SURVIVED* row(s) excluded — the labelled-benign statusRecorder\n"
              f"    default, which changes log output and nothing else.)")
    print("   BOUNDED, not exact: sweep rows carry no line number, so a file with mixed cold\n"
          "   and warm sites can only be bounded. Adding the line makes the join exact.\n"
          "   SEQUENCING, and it is not 'whenever': do it AFTER the v4-vs-v5 diff, never\n"
          "   before. _redraw_diff parses rows POSITIONALLY and hard-fails on anything but\n"
          "   exactly 4 tab-separated fields, so a 5-column v5 file against a 4-column v4\n"
          "   file stops the capstone comparison dead. It fails LOUDLY, which is the right\n"
          "   design and the opposite of the failure mode this session kept finding — but it\n"
          "   would fail at the worst possible moment.")

    print("\nWHAT THE ROW DELTA IS NOT: not the corpus getting worse, not new holes. The trees\n"
          "are frozen and unchanged. It is the size of the question five of six shapes were\n"
          "never asked, because they walked glob(\"*.go\") and every internal/ artifact\n"
          "matched nothing. Every added row still needs adjudicating, and tonight's own\n"
          "numbers say most will not be holes: 24% of sites sit on never-executed lines and\n"
          "the dead 500-else class dominates that.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
