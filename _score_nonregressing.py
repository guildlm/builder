#!/usr/bin/env python3
"""Score the non-regressing repair gate against the green-requiring one, case by case.

    python _score_nonregressing.py [--before FILE] [--after FILE] [--verify-green]
    python _score_nonregressing.py --self-test

Pre-registration: logs/PREREG-a-non-regressing-repair-gate.txt.
    PRIMARY   of the 59 RED-BEFORE / REVERTED cases, at least 45 accepted under the new gate.
    REJECT    the 11 GREEN-BEFORE fills stay 11, and no green tree ends red.
    REJECT    no accepted move leaves a NEW (file, message) pair — true by construction, so a
              violation means the comparison key is broken.

WHY A JOIN AND NOT TWO RATES. The two runs are the same 74 cases measured under different gates, so
the result is a TRANSITION per case, not a before-percentage next to an after-percentage. A rate
comparison would also hide the only genuinely bad outcome — a case that was FILLED under the strict
gate and is REVERTED under the weaker one, which cannot happen by construction and therefore must be
looked for.

⚠️ THE FIRST RUN'S TSV IS MISSING green_after. It was written before the reject condition needed that
column, so "no green tree ends red" cannot be read off the pair of files; `--verify-green` re-derives
it by running the toolchain over the green-before trees. That flag shells out to Go and is the reason
this tool carries no blanket slow marker: without it, the scoring is pure text.
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))
import builder  # noqa: E402

BEFORE = "logs/repair-survival.tsv"
AFTER = "logs/repair-survival-nonregressing.tsv"


def load(path: str) -> dict[tuple[str, str], dict]:
    """Rows keyed by (tree, path). Tolerates both the 5-column layout and the
    6-column one that added green_after — the column count IS the version."""
    rows: dict[tuple[str, str], dict] = {}
    for line in pathlib.Path(path).read_text().splitlines():
        if not line.strip():
            continue
        f = line.split("\t")
        if len(f) == 5:
            outcome, green_before, tree, p, take = f
            green_after = ""
        elif len(f) == 6:
            outcome, green_before, green_after, tree, p, take = f
        else:
            raise SystemExit(f"{path}: unexpected {len(f)} columns: {line[:80]}")
        rows[(tree, p)] = {
            "outcome": outcome, "green_before": green_before == "True",
            "green_after": green_after, "take": take,
        }
    return rows


def verify_green(trees: list[str]) -> list[tuple[str, bool]]:
    """Re-run the pass on a COPY of each named tree and report whether it is still
    green afterwards. Only called for green-before trees, and only under a flag."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "rs", pathlib.Path(__file__).resolve().parent / "_repair_survival.py")
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    toolchain = builder.GoToolchain()
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="score-nonreg-"))
    out = []
    for name in trees:
        recs = rs.run_tree(pathlib.Path("generated") / name, scratch, toolchain)
        out.append((name, all(r["green_after"] for r in recs) if recs else True))
    shutil.rmtree(scratch, ignore_errors=True)
    return out


def report(args) -> int:
    before, after = load(args.before), load(args.after)
    shared = sorted(set(before) & set(after))
    print(f"{len(before)} cases before · {len(after)} after · {len(shared)} joined\n")

    matrix = collections.Counter(
        (before[k]["outcome"], after[k]["outcome"]) for k in shared)
    print("  transition (green-requiring -> non-regressing):")
    for (b, a), n in sorted(matrix.items(), key=lambda x: -x[1]):
        mark = "  <-- REGRESSION" if (b == "FILLED" and a != "FILLED") else ""
        print(f"    {b:9s} -> {a:9s}  {n:3d}{mark}")

    red_rev = [k for k in shared
               if not before[k]["green_before"] and before[k]["outcome"] == "REVERTED"]
    won = [k for k in red_rev if after[k]["outcome"] == "FILLED"]
    print(f"\n  PRIMARY  red-before REVERTED cases: {len(red_rev)} · now FILLED: {len(won)}"
          f"  (pre-registered: at least 45)")
    print(f"           -> {'HELD' if len(won) >= 45 else 'MISSED'}")

    green_fills_b = [k for k in shared
                     if before[k]["green_before"] and before[k]["outcome"] == "FILLED"]
    green_fills_a = [k for k in green_fills_b if after[k]["outcome"] == "FILLED"]
    print(f"\n  REJECT   green-before fills: {len(green_fills_b)} before · "
          f"{len(green_fills_a)} after"
          f"  -> {'clear' if len(green_fills_a) == len(green_fills_b) else 'TRIPPED'}")

    regressions = [k for k in shared
                   if before[k]["outcome"] == "FILLED" and after[k]["outcome"] != "FILLED"]
    print(f"  REJECT   FILLED -> not-FILLED: {len(regressions)}"
          f"  -> {'clear' if not regressions else 'TRIPPED ' + str(regressions)}")

    missing = [k for k in shared if after[k]["green_before"] and not after[k]["green_after"]]
    if missing:
        print(f"\n  ⚠️ green_after absent for {len(missing)} green-before cases — the TSV predates "
              f"the column. Re-derive with --verify-green.")
    if args.verify_green:
        trees = sorted({k[0] for k in shared if after[k]["green_before"]})
        print(f"\n  verifying {len(trees)} green-before trees still end green...")
        bad = [n for n, ok in verify_green(trees) if not ok]
        print(f"  -> {'clear — none went red' if not bad else 'TRIPPED: ' + ', '.join(bad)}")
    return 0


def self_test() -> int:
    """Fixed rows. The row that matters is the one that CANNOT happen: a case the
    strict gate filled and the weaker gate refused. If the scorer cannot see that,
    it cannot clear the reject condition it exists to check."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="score-self-"))
    b = tmp / "b.tsv"
    a = tmp / "a.tsv"
    b.write_text(
        "REVERTED\tFalse\tt1\tp.go\tX\n"
        "FILLED\tTrue\tt2\tp.go\tX\n"
        "FILLED\tTrue\tt3\tp.go\tX\n"
        "NO-DONOR\tFalse\tt4\tp.go\t\n"
        "REVERTED\tFalse\tt5\tp.go\tX\n"
        "REVERTED\tFalse\tt6\tp.go\tX\n"
    )
    # the AFTER file speaks the three-state vocabulary the tool gained after the first
    # run — REFUSED and NOT-ATTEMPTED where there used to be one REVERTED. A scorer that
    # only knew the old labels would silently count these as neither win nor regression.
    a.write_text(
        "FILLED\tFalse\tTrue\tt1\tp.go\tX\n"           # the intended win
        "FILLED\tTrue\tTrue\tt2\tp.go\tX\n"
        "REVERTED\tTrue\tTrue\tt3\tp.go\tX\n"          # the impossible regression
        "NO-DONOR\tFalse\tFalse\tt4\tp.go\t\n"
        "REFUSED\tFalse\tFalse\tt5\tp.go\tX\n"         # the gate's decision
        "NOT-ATTEMPTED\tFalse\tFalse\tt6\tp.go\tX\n"   # never the gate's decision
    )
    rb, ra = load(str(b)), load(str(a))
    shared = set(rb) & set(ra)
    regressions = [k for k in shared
                   if rb[k]["outcome"] == "FILLED" and ra[k]["outcome"] != "FILLED"]
    wins = [k for k in shared
            if not rb[k]["green_before"] and rb[k]["outcome"] == "REVERTED"
            and ra[k]["outcome"] == "FILLED"]
    shutil.rmtree(tmp, ignore_errors=True)
    failures = 0
    if regressions != [("t3", "p.go")]:
        failures += 1
        print(f"FAIL: regression not detected, got {regressions}")
    if wins != [("t1", "p.go")]:
        failures += 1
        print(f"FAIL: win not detected, got {wins}")
    labels = {ra[k]["outcome"] for k in shared}
    if not {"REFUSED", "NOT-ATTEMPTED"} <= labels:
        failures += 1
        print(f"FAIL: three-state labels not round-tripped, saw {sorted(labels)}")
    if ra[("t2", "p.go")]["green_after"] != "True":
        failures += 1
        print("FAIL: green_after not parsed from the six-column layout")
    if len(load(str(b)) if b.exists() else {}) not in (0, 4):
        failures += 1
    print("self-test:", "OK — the win is counted and the impossible regression is caught"
          if not failures else f"{failures} FAILED")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", default=BEFORE)
    ap.add_argument("--after", default=AFTER)
    ap.add_argument("--verify-green", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    return report(args)


if __name__ == "__main__":
    raise SystemExit(main())
