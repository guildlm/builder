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
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import _arm_table  # noqa: E402

HERE = pathlib.Path(__file__).parent
BASELINE = "specs/ledger-origorder-baseline.yaml"

# The three processes that passed BOTH gates (ABSENT at baseline, null on the content-free
# screen). Nothing else is poolable: 10 August's placebo screen disqualified 3 of 4 informative
# processes, and the unscreened series cannot separate treatment from process.
SERIES = [("p1", "46375", "s-"), ("p2", "71833", "r2-"), ("p3", "4691", "p3-"),
          ("p4", "4970", "f-"), ("p5", "36921", "p5-")]

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

# ⚠️ CONSTRUCTION FAMILY — added 15 August, when pid 36921 returned ABSENT for all FIVE arms of one
# construction (+14 through +20) and LONG for all THREE arms that are built differently, including
# one at the IDENTICAL +20 in the IDENTICAL two regions. Size cannot express that split; this can.
#
# ⚠️ DECLARED **AND** DERIVED, AND A DISAGREEMENT STOPS THE TALLY. The location table above is
# declared-only because "where the edit lands" is not recoverable from the spec text. Family IS
# recoverable — it is literally what the heading says — so declaring it alone would throw away a
# free check. The ladder's signature is the byte-identical noun phrase followed by the extended
# quantifier; every rung of it renders "Sentinel error values, all <adverb> matchable", and no
# other arm in the archive does.
# ⚠️ A SUBSTRING IS NOT A CONSTRUCTION. The first version of this derivation tested for
# "Sentinel error values, all " and REFUSED on its first real run, correctly: L3 (+6, the noun
# phrase alone, quantifier left as a bare "all") and L4 (which also rewrites "with" -> "via")
# both contain that substring and neither is a rung. A rung is the whole shape — region one
# rewritten, region two extended by a NON-EMPTY adverb, and nothing else in the heading touched.
# L4 is the arm whose verdict varies across processes, so a loose signature would have quietly
# imported the campaign's one known unstable arm into the family being called uniformly null.
LADDER_RE = re.compile(r"Sentinel error values, all (\w[\w ]*) matchable with errors\.Is")
FAMILY = {
    "ledger-linedose-6.yaml": "quantifier ladder",    # +14  "all readily"
    "ledger-linefloor-1.yaml": "quantifier ladder",   # +15  "all reliably"
    "ledger-linefloor-2.yaml": "quantifier ladder",   # +17  "all so readily"
    "ledger-linefloor-3.yaml": "quantifier ladder",   # +19  "all very readily"
    "ledger-linefloor-4.yaml": "quantifier ladder",   # +20  "all quite readily"
}


def family_of(spec: str) -> str:
    """Declared family, cross-checked against the spec's own rendered purpose."""
    declared = FAMILY.get(spec, "other rewrite")
    p = HERE / "specs" / spec
    if not p.is_file():
        raise _arm_table.Refuse(f"{spec}: no such spec, cannot verify its family")
    import yaml
    purpose = ""
    for f in yaml.safe_load(p.read_text())["files"]:
        if f["path"] == "internal/models/models.go":
            purpose = f["purpose"]
    derived = "quantifier ladder" if LADDER_RE.search(purpose) else "other rewrite"
    if declared != derived:
        raise _arm_table.Refuse(
            f"{spec}: declared family {declared!r} but its purpose says {derived!r} — one of the "
            f"two is wrong and guessing which is how a family table becomes fiction")
    return declared


def rows_for(name, pid, prefix):
    rows = _arm_table.build(HERE, prefix, BASELINE, pid=pid)
    for r in rows:
        spec = r["spec"]
        if spec not in LOCATION:
            raise _arm_table.Refuse(
                f"{name}/{r['label']}: spec {spec} has no declared location — add it to LOCATION "
                f"rather than letting it fall into a bucket by accident")
        r["series"], r["location"] = name, LOCATION[spec]
        r["family"] = family_of(spec)
    return rows


def cross(rows):
    """(family, size bucket) -> counts, pooled, ON-LINE arms only.

    ⚠️ THIS IS THE TABLE THE 15 AUGUST CLAIM RESTS ON and it exists because I derived its headline
    number in my head first. "On-line arms of >=+20 reach LONG 13 of 15" is true and useless: the
    two exceptions are both the same ladder arm, and splitting the same rows by construction turns
    a ragged size rule into two clean ones. Computing it is not optional.
    """
    out = {}
    for r in rows:
        if r["location"] != "on-line":
            continue
        d = int(r["delta"])
        bucket = "<=+14" if d <= 14 else (">=+20" if d >= 20 else "the gap (+15..+19)")
        c = out.setdefault((r["family"], bucket), {"n": 0, "long": 0, "nonnull": 0, "arms": []})
        c["n"] += 1
        c["long"] += r["verdict"] == "LONG"
        c["nonnull"] += r["verdict"] != "ABSENT"
        c["arms"].append(f"{r['series']}/{r['label']} {r['delta']} {r['verdict'].split(':')[0]}")
    return out


def by_family(rows):
    """(series, family) -> counts, over ON-LINE treated arms only.

    ⚠️ RESTRICTED TO ON-LINE ARMS ON PURPOSE. The ladder only ever edits the declaration line, so
    pooling it against off-line arms would compare a construction with a location and credit the
    difference to whichever of the two the sentence happened to name.
    """
    out = {}
    for r in rows:
        if r["location"] != "on-line":
            continue
        c = out.setdefault((r["series"], r["family"]), {"n": 0, "long": 0, "nonnull": 0, "arms": []})
        c["n"] += 1
        c["long"] += r["verdict"] == "LONG"
        c["nonnull"] += r["verdict"] != "ABSENT"
        c["arms"].append(f"{r['label']} {r['delta']} {r['verdict'].split(':')[0]}")
    return out


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

    # ⚠️ TOTALS ARE PRINTED BECAUSE I ADDED THEM UP BY HAND ONCE AND GOT 12 WHERE THE BUCKETS SAY
    # 14. The per-bucket rows are the finding; the per-LOCATION totals are what a summary sentence
    # quotes, and a summary sentence is exactly where a hand-added number goes unchallenged.
    print()
    for loc in sorted({k[0] for k in t}):
        n = sum(c["n"] for k, c in t.items() if k[0] == loc)
        lo = sum(c["long"] for k, c in t.items() if k[0] == loc)
        nn = sum(c["nonnull"] for k, c in t.items() if k[0] == loc)
        print(f"    {loc:<14} {'ALL SIZES':<20} {n:>3}  {lo:>6} of {n:<4}  {nn:>6} of {n:<4}")

    # THE CONSTRUCTION SPLIT, per process, on-line arms only. Per process rather than pooled
    # because 11 August established the wording->outcome map is process-specific, and a pooled
    # family table would hide exactly the thing 15 August found: the split is CLEAN on one
    # process and absent on another.
    print(f"\n    {'process':<9} {'construction family':<22} {'n':>3}  "
          f"{'reached LONG':>13}  {'above ABSENT':>13}   sizes")
    f = by_family(rows)
    for key in sorted(f, key=lambda k: (k[0], k[1])):
        c = f[key]
        sizes = ",".join(sorted((a.split()[1] for a in c["arms"]), key=lambda s: int(s)))
        print(f"    {key[0]:<9} {key[1]:<22} {c['n']:>3}  "
              f"{c['long']:>6} of {c['n']:<4}  {c['nonnull']:>6} of {c['n']:<4}   {sizes}")
        if a.verbose:
            for arm in c["arms"]:
                print(f"        {arm}")

    print(f"\n    {'construction family':<22} {'size':<20} {'n':>3}  "
          f"{'reached LONG':>13}  {'above ABSENT':>13}")
    x = cross(rows)
    for key in sorted(x, key=lambda k: (k[0], k[1])):
        c = x[key]
        print(f"    {key[0]:<22} {key[1]:<20} {c['n']:>3}  "
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

    # 3. FAMILY must be derived from the spec on disk, not taken on the declaration's word
    chk("a ladder rung derives as the ladder",
        family_of("ledger-linefloor-4.yaml"), "quantifier ladder")
    chk("the +14 low anchor is the same construction as the rungs",
        family_of("ledger-linedose-6.yaml"), "quantifier ladder")
    # ⚠️ the paraphrase shares the ladder's NOUN PHRASE and must still not be counted as a rung —
    # that shared region is precisely why the two are comparable, and precisely how a sloppy
    # substring test would swallow the one arm the split turns on.
    chk("the +20 paraphrase is NOT a ladder rung",
        family_of("ledger-sentinelline-placebo.yaml"), "other rewrite")
    chk("A+C is not a ladder rung", family_of("ledger-origorder-ac.yaml"), "other rewrite")
    # ⚠️ THE TWO ARMS THAT BROKE THE FIRST DERIVATION, pinned so they cannot break it again.
    chk("L3 (+6, noun phrase alone, bare 'all') is NOT a rung — the adverb slot is empty",
        family_of("ledger-linedose-3.yaml"), "other rewrite")
    chk("L4 (also rewrites 'with'->'via') is NOT a rung — it touches a third region",
        family_of("ledger-linedose-4.yaml"), "other rewrite")
    chk("the shipped arm is not a ladder rung", family_of("ledger-origorder.yaml"), "other rewrite")

    # 4. a declaration that disagrees with the spec text must STOP the tally
    FAMILY["ledger-sentinelline-placebo.yaml"] = "quantifier ladder"
    try:
        family_of("ledger-sentinelline-placebo.yaml")
        ok = False
        print("  FAIL a declared/derived family disagreement did NOT stop the tally")
    except _arm_table.Refuse:
        print("  ok   a declared/derived family disagreement stops the tally")
    finally:
        del FAMILY["ledger-sentinelline-placebo.yaml"]

    # 5. the family table must ignore off-line arms rather than credit them to a construction
    ff = by_family([
        {"series": "x", "label": "a", "delta": "+20", "verdict": "LONG",
         "location": "on-line", "family": "other rewrite"},
        {"series": "x", "label": "b", "delta": "+20", "verdict": "ABSENT",
         "location": "on-line", "family": "quantifier ladder"},
        {"series": "x", "label": "c", "delta": "+54", "verdict": "ABSENT",
         "location": "off-line", "family": "other rewrite"},
    ])
    chk("off-line arms are excluded from the family table",
        ff[("x", "other rewrite")]["n"], 1)
    xx = cross([
        {"series": "x", "label": "a", "delta": "+20", "verdict": "LONG",
         "location": "on-line", "family": "other rewrite"},
        {"series": "x", "label": "b", "delta": "+20", "verdict": "ABSENT",
         "location": "on-line", "family": "quantifier ladder"},
        {"series": "x", "label": "c", "delta": "+54", "verdict": "LONG",
         "location": "off-line", "family": "other rewrite"},
    ])
    chk("the cross-tab splits one size bucket by family",
        (xx[("other rewrite", ">=+20")]["long"], xx[("quantifier ladder", ">=+20")]["long"]),
        (1, 0))
    chk("the cross-tab excludes off-line arms too",
        sum(c["n"] for c in xx.values()), 2)
    chk("the two on-line families are kept apart",
        (ff[("x", "quantifier ladder")]["long"], ff[("x", "other rewrite")]["long"]), (0, 1))

    # 3. the four floor rungs must be declared BEFORE they are drawn, or the first table that
    #    includes them refuses in the middle of a live series
    for k in ("1", "2", "3", "4"):
        chk(f"linefloor-{k} has a declared location",
            LOCATION.get(f"ledger-linefloor-{k}.yaml"), "on-line")

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
