#!/usr/bin/env python3
"""Pool the three screened processes' arms by SIZE and LOCATION, so the floor claim is computed.

    ./_size_floor_tally.py
    ./_size_floor_tally.py --self-test

WHY THIS EXISTS. The claim that motivates the size-floor experiment — "on-line arms of +20 or
more reach LONG 8 times out of 8, arms of +14 or less only 2 times out of 14" — was counted by
eye off three arm tables on 11 August. This campaign has produced seven wrong numbers from
hand-built filters, two of them caught only after publication, and the standing rule is that a
number appearing in a result log is computed by an instrument that has its own self-test.

WHAT IT DOES. It calls `_arm_table.build` once per screened series, so every row it counts has
already passed that tool's four-way cross-check (ledger row · re-classified tree · re-scanned
probe log · delta computed from the two yamls). It then buckets by:

    LOCATION  declared per spec, NOT inferred. A spec this file has never heard of stops the
              tally rather than landing in a default bucket — mis-bucketing one arm is exactly
              how the 8/8 could become 8/9 without anyone noticing.
    SIZE      the delta computed at the target purpose.

AND IT REPORTS TWO TALLIES, not one. "Flip" has been used in this campaign to mean "reached
LONG", but the outcome is three-valued, and at the finer resolution the small-edit bucket is not
as empty as the binary count suggests. Both numbers are printed side by side so a reader cannot
take the convenient one for the whole story.

⚠️ POOLING ACROSS PROCESSES IS THE KNOWN WEAKNESS OF THIS TALLY, not a detail. 10 and 11 August
established that the wording->outcome map is process-specific: the same +5 arm is ABBREVIATED on
p1, LONG on p2 and ABBREVIATED on p3. A pooled count can therefore only motivate an experiment;
it cannot locate a floor. The floor has to be bracketed against ONE process's own anchors.
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import _arm_table  # noqa: E402

HERE = pathlib.Path(__file__).parent
BASELINE = "specs/ledger-origorder-baseline.yaml"

# The three processes that passed BOTH gates (ABSENT at baseline, null on the content-free
# screen). Nothing else is poolable: 10 August's placebo screen disqualified 3 of 4 informative
# processes, and the unscreened series cannot separate treatment from process.
SERIES = [("p1", "46375", "s-"), ("p2", "71833", "r2-"), ("p3", "4691", "p3-")]

# ⚠️ DECLARED, NOT INFERRED. Every spec that can appear in these series is named here with where
# its edit lands relative to the declaration line in models.go's purpose.
LOCATION = {
    "ledger-origorder-baseline.yaml": "baseline",
    "ledger-origorder.yaml": "on-line",
    "ledger-origorder-varonly.yaml": "on-line",
    "ledger-origorder-ac.yaml": "on-line",
    "ledger-sentinelline-placebo.yaml": "on-line",
    "ledger-linedose-1.yaml": "on-line",
    "ledger-linedose-2.yaml": "on-line",
    "ledger-linedose-3.yaml": "on-line",
    "ledger-linedose-4.yaml": "on-line",
    "ledger-linedose-5.yaml": "on-line",
    "ledger-linedose-6.yaml": "on-line",
    "ledger-linefloor-1.yaml": "on-line",
    "ledger-linefloor-2.yaml": "on-line",
    "ledger-linefloor-3.yaml": "on-line",
    "ledger-linefloor-4.yaml": "on-line",
    "ledger-ownplacebo.yaml": "off-line",        # +54, sentences ABOVE, names no sentinel
    "ledger-belowline-placebo.yaml": "off-line",  # +21, one sentence BELOW, names ErrInvalid
    "ledger-jobstrip.yaml": "other-purpose",      # three files away, in store.go
    "ledger-jobstrip-placebo.yaml": "other-purpose",
}


def rows_for(name, pid, prefix):
    rows = _arm_table.build(HERE, prefix, BASELINE, pid=pid)
    for r in rows:
        spec = r["spec"]
        if spec not in LOCATION:
            raise _arm_table.Refuse(
                f"{name}/{r['label']}: spec {spec} has no declared location — add it to LOCATION "
                f"rather than letting it fall into a bucket by accident")
        r["series"], r["location"] = name, LOCATION[spec]
    return rows


def tally(rows):
    """(location, size predicate) -> counts of LONG and of above-ABSENT, over treated arms."""
    out = {}
    for r in rows:
        if r["location"] in ("baseline", "other-purpose"):
            continue  # baselines have no size; other-purpose deltas are not measured at target
        d = int(r["delta"])
        bucket = "<=+14" if d <= 14 else (">=+20" if d >= 20 else "the gap (+15..+19)")
        key = (r["location"], bucket)
        c = out.setdefault(key, {"n": 0, "long": 0, "nonnull": 0, "arms": []})
        c["n"] += 1
        c["long"] += r["verdict"] == "LONG"
        c["nonnull"] += r["verdict"] != "ABSENT"
        c["arms"].append(f"{r['series']}/{r['label']} {r['delta']} {r['verdict'].split(':')[0]}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    rows = []
    for name, pid, prefix in SERIES:
        try:
            rows += rows_for(name, pid, prefix)
        except _arm_table.Refuse as e:
            print(f"REFUSING ({name}, pid {pid}): {e}")
            return 2

    print(f"  pooled over {len(SERIES)} screened processes, {len(rows)} ledger rows\n")
    print(f"    {'location':<14} {'size':<20} {'n':>3}  {'reached LONG':>13}  {'above ABSENT':>13}")
    t = tally(rows)
    for key in sorted(t, key=lambda k: (k[0], k[1])):
        c = t[key]
        print(f"    {key[0]:<14} {key[1]:<20} {c['n']:>3}  "
              f"{c['long']:>6} of {c['n']:<4}  {c['nonnull']:>6} of {c['n']:<4}")
        if a.verbose:
            for arm in c["arms"]:
                print(f"        {arm}")
    return 0


def self_test() -> int:
    ok = True

    def chk(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: got {got!r} want {want!r}")
        else:
            print(f"  ok   {name}")

    # 1. the buckets must be computed from a KNOWN input, independent of what is on disk today
    fake = [
        {"series": "x", "label": "a", "spec": "s", "delta": "+51", "verdict": "LONG",
         "location": "on-line"},
        {"series": "x", "label": "b", "spec": "s", "delta": "+14", "verdict": "ABSENT",
         "location": "on-line"},
        {"series": "x", "label": "c", "spec": "s", "delta": "+5", "verdict": "ABBREVIATED:ErrI",
         "location": "on-line"},
        {"series": "x", "label": "d", "spec": "s", "delta": "+17", "verdict": "LONG",
         "location": "on-line"},
        {"series": "x", "label": "e", "spec": "s", "delta": "+0", "verdict": "ABSENT",
         "location": "baseline"},
    ]
    t = tally(fake)
    chk("baselines are excluded", ("baseline", "<=+14") in t, False)
    chk("+51 buckets as >=+20", t[("on-line", ">=+20")]["n"], 1)
    chk("+17 buckets into the gap", t[("on-line", "the gap (+15..+19)")]["long"], 1)
    chk("+14 buckets as <=+14", t[("on-line", "<=+14")]["n"], 2)
    # ⚠️ THE DISTINCTION THE BINARY COUNT LOSES: ABBREVIATED is not LONG but is not ABSENT.
    chk("ABBREVIATED counts as above-ABSENT, not as LONG",
        (t[("on-line", "<=+14")]["long"], t[("on-line", "<=+14")]["nonnull"]), (0, 1))

    # 2. an undeclared spec must STOP the tally rather than be bucketed
    import types
    saved = _arm_table.build
    _arm_table.build = lambda *a, **k: [{"label": "z", "spec": "ledger-unheard-of.yaml",
                                         "delta": "+9", "verdict": "ABSENT", "pid": "1"}]
    try:
        rows_for("t", "1", "z-")
        ok = False
        print("  FAIL an undeclared spec did NOT stop the tally")
    except _arm_table.Refuse:
        print("  ok   an undeclared spec stops the tally")
    finally:
        _arm_table.build = saved
    del types

    # 3. the four floor rungs must be declared BEFORE they are drawn, or the first table that
    #    includes them refuses in the middle of a live series
    for k in ("1", "2", "3", "4"):
        chk(f"linefloor-{k} has a declared location",
            LOCATION.get(f"ledger-linefloor-{k}.yaml"), "on-line")

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
