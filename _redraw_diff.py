#!/usr/bin/env python3
"""Compare two corpus sweeps: what does a full REGENERATION change about the verdicts?

The durability programme has been asking "does this closure survive the next run?" one spec
at a time, and had answered it for two of five. Rebuilding the whole corpus answers it for
every spec at once: the same specs, the same model, a week apart, every artifact redrawn.
The rows file is git-tracked precisely so that comparison exists — this reduces it to a
table instead of a 170-line diff nobody reads.

    python _redraw_diff.py logs/hole-hunt-rows.tsv logs/hole-hunt-rows-new.tsv
    python _redraw_diff.py --self-test

WHAT IT REFUSES TO DO
  A row is (artifact, file, shape, verdict). Only rows whose FIRST THREE fields appear in
  both sweeps are comparable; everything else is a site that moved, appeared or vanished —
  which is a finding of its own and not a verdict change. Both denominators are printed,
  because "3 flips" out of 12 comparable rows and out of 150 rows are different sentences,
  and the corpus headline has already been wrong once for exactly this reason
  (FINDING-status-code-holes: 64 of 150 probes could answer, not 150).
"""
from __future__ import annotations

import collections
import pathlib
import sys

DEAD = ("BASELINE-RED", "NOAPPLY", "SKIP")


def load(path: pathlib.Path) -> dict[tuple[str, str, str], str]:
    rows: dict[tuple[str, str, str], str] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 4:
            raise SystemExit(f"{path}: expected 4 tab-separated fields, got {len(parts)}:\n  {line}")
        art, f, shape, verdict = parts
        rows[(art, f, shape)] = verdict
    return rows


def compare(old: dict, new: dict) -> dict:
    both = sorted(set(old) & set(new))
    flips = [(k, old[k], new[k]) for k in both if old[k] != new[k]]
    # A flip between two DEAD verdicts (NOAPPLY -> BASELINE-RED) says nothing about
    # defence; separate it so it cannot pad the headline.
    live = [f for f in flips if not (f[1] in DEAD and f[2] in DEAD)]
    return {
        "comparable": both,
        "flips": flips,
        "live_flips": live,
        "gone": sorted(set(old) - set(new)),
        "fresh": sorted(set(new) - set(old)),
        "transitions": collections.Counter((o, n) for _, o, n in flips),
    }


def render(res: dict, old: dict, new: dict) -> str:
    out = []
    out.append(f"rows: {len(old)} old · {len(new)} new · {len(res['comparable'])} COMPARABLE "
               f"(same artifact+file+shape in both)")
    out.append(f"      {len(res['gone'])} site(s) only in the old sweep, "
               f"{len(res['fresh'])} only in the new — moved, added or lost, NOT verdict changes")
    out.append(f"flips: {len(res['flips'])} of {len(res['comparable'])} comparable "
               f"({len(res['live_flips'])} involving a live verdict)")
    if res["transitions"]:
        out.append("")
        for (o, n), c in sorted(res["transitions"].items(), key=lambda kv: -kv[1]):
            tag = "  (both dead — says nothing about defence)" if o in DEAD and n in DEAD else ""
            out.append(f"   {c:>3}  {o:<13} -> {n}{tag}")
    lost = [(k, o, n) for k, o, n in res["live_flips"] if o == "CAUGHT" and n == "SURVIVED"]
    won = [(k, o, n) for k, o, n in res["live_flips"] if o == "SURVIVED" and n == "CAUGHT"]
    if lost:
        out.append("\n   DEFENCE LOST in the redraw (was CAUGHT, now SURVIVED):")
        for (a, f, s), _, _ in lost:
            out.append(f"      {a:<28} {f:<18} {s}")
    if won:
        out.append("\n   DEFENCE GAINED in the redraw (was SURVIVED, now CAUGHT):")
        for (a, f, s), _, _ in won:
            out.append(f"      {a:<28} {f:<18} {s}")
    if not res["comparable"]:
        out.append("\n   NOTHING WAS COMPARED. Every site moved or changed shape, so this "
                   "says nothing\n   about durability — it says the two sweeps do not "
                   "describe the same corpus.")
    return "\n".join(out)


def self_test() -> int:
    """Plant every transition this is supposed to separate, and require it to separate them."""
    old = {("a-v4", "h.go", "drop X"): "CAUGHT",       # -> SURVIVED  (defence lost)
           ("b-v4", "h.go", "drop X"): "SURVIVED",     # -> CAUGHT    (defence gained)
           ("c-v4", "h.go", "drop X"): "CAUGHT",       # unchanged
           ("d-v4", "h.go", "drop X"): "NOAPPLY",      # -> BASELINE-RED (both dead)
           ("e-v4", "h.go", "drop X"): "CAUGHT"}       # site vanishes
    new = {("a-v4", "h.go", "drop X"): "SURVIVED",
           ("b-v4", "h.go", "drop X"): "CAUGHT",
           ("c-v4", "h.go", "drop X"): "CAUGHT",
           ("d-v4", "h.go", "drop X"): "BASELINE-RED",
           ("f-v4", "h.go", "drop X"): "CAUGHT"}       # a site that is new
    res = compare(old, new)
    fail = []
    if len(res["comparable"]) != 4:
        fail.append(f"comparable should be 4 (e/f are not shared), got {len(res['comparable'])}")
    if len(res["flips"]) != 3:
        fail.append(f"3 verdicts changed, got {len(res['flips'])}")
    if len(res["live_flips"]) != 2:
        fail.append(f"the NOAPPLY->BASELINE-RED flip must not count as live, got "
                    f"{len(res['live_flips'])} live")
    if [k for k, o, n in res["live_flips"] if o == "CAUGHT" and n == "SURVIVED"] != \
            [("a-v4", "h.go", "drop X")]:
        fail.append("the CAUGHT->SURVIVED row is not reported as defence lost")
    if len(res["gone"]) != 1 or len(res["fresh"]) != 1:
        fail.append("a vanished site and a new site must be counted separately from flips")
    # And the denominator rule: two sweeps sharing NOTHING must say so rather than print 0 flips.
    empty = compare({("x-v4", "h.go", "s"): "CAUGHT"}, {("y-v4", "h.go", "s"): "CAUGHT"})
    if "NOTHING WAS COMPARED" not in render(empty, {}, {}):
        fail.append("two sweeps with no shared row must refuse, not report '0 flips'")
    for f in fail:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fail else "ok — every planted transition separated"))
    return 1 if fail else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    o, n = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    for p in (o, n):
        if not p.is_file():
            raise SystemExit(f"{p} is not a file")
    old, new = load(o), load(n)
    print(render(compare(old, new), old, new))
