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
import _mkvariant_construction_axis as _consaxis  # noqa: E402

HERE = pathlib.Path(__file__).parent
BASELINE = "specs/ledger-origorder-baseline.yaml"

# The three processes that passed BOTH gates (ABSENT at baseline, null on the content-free
# screen). Nothing else is poolable: 10 August's placebo screen disqualified 3 of 4 informative
# processes, and the unscreened series cannot separate treatment from process.
SERIES = [("p1", "46375", "s-"), ("p2", "71833", "r2-"), ("p3", "4691", "p3-"),
          ("p4", "4970", "f-"), ("p5", "36921", "p5-"),
          # p6 is a THREE-ROW series: baseline, screen, anchor. The GPU killed the process on its
          # fourth draw, before any axis arm. It is listed because its anchor row is real and
          # counts, and leaving it out because the session was cut short is how a pooled table
          # quietly becomes a table of the sessions that went well.
          ("p6", "68231", "ax-")]

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
    "ledger-consaxis-pad1.yaml": "on-line",      # +20, "all of them below"  (pad, non-adverbial)
    "ledger-consaxis-rep1.yaml": "on-line",      # +20, "each one of these"  (replacement)
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

# ⚠️ THE AXIS — added 16 August. The family table above answers "is this arm the adverb ladder?",
# which is a question about ONE construction, and 15 August's own limit note said so: one inert
# family is an anecdote about a family. The axis asks the GENERAL question the ladder was only an
# instance of — does the arm KEEP the base quantifier and pad it, or REPLACE it? — and it is
# derived by the same module that builds the new arms, so the tally and the specs cannot drift
# apart into two different definitions of the same word.
#
#   quantifier pad          slot starts with the token "all" and is longer than it
#   quantifier replacement  slot is of the right shape but "all" is gone
#   no quantifier edit      slot is exactly "all" (the noun-phrase-only arms, and the baseline)
#   not a quantifier-slot arm   the heading shape does not match at all (tail rewritten, or the
#                               whole line rebuilt, or the edit is not on the line)
#
# ⚠️ DECLARED FOR **EVERY** SPEC THE TALLY WILL COUNT, and a disagreement with the derivation
# stops the tally, exactly as with FAMILY. The declaration is not redundant: it is what makes
# adding a spec to LOCATION force a decision about what construction it is, instead of letting
# the regex decide silently. The check that matters is that the two never disagree.
AXIS = {
    "ledger-origorder-baseline.yaml": "no quantifier edit",
    "ledger-linedose-3.yaml": "no quantifier edit",        # +6, noun phrase alone
    "ledger-linedose-2.yaml": "quantifier pad",            # +8, "all of them", tail intact
    "ledger-linedose-6.yaml": "quantifier pad",            # +14 adverb
    "ledger-linefloor-1.yaml": "quantifier pad",           # +15 adverb
    "ledger-linefloor-2.yaml": "quantifier pad",           # +17 adverb
    "ledger-linefloor-3.yaml": "quantifier pad",           # +19 adverb
    "ledger-linefloor-4.yaml": "quantifier pad",           # +20 adverb
    "ledger-consaxis-pad1.yaml": "quantifier pad",         # +20 NON-adverbial  <- new
    "ledger-sentinelline-placebo.yaml": "quantifier replacement",   # +20 "every one of them"
    "ledger-consaxis-rep1.yaml": "quantifier replacement",          # +20 "each one of these"
    # ⚠️ L5 (+13) retains "all" and pads it non-adverbially and is LONG on p1 — it is NOT a pad
    # arm here because it also rewrites the tail (with -> via) and therefore moves three regions.
    # It is the archive row most hostile to the pad hypothesis and it is declared, not omitted.
    "ledger-linedose-5.yaml": "not a quantifier-slot arm",
    "ledger-linedose-1.yaml": "not a quantifier-slot arm",  # -1, tail only
    "ledger-linedose-4.yaml": "not a quantifier-slot arm",  # +5, the cross-process-unstable arm
    # the two big rewrites replace the whole heading ("Exported sentinels, ..."), so the shape
    # this axis is about is not present in them at all
    "ledger-origorder.yaml": "not a quantifier-slot arm",
    "ledger-origorder-ac.yaml": "not a quantifier-slot arm",
    # ⚠️ THESE FIVE LEAVE THE QUANTIFIER SLOT ALONE and that is a fact about them worth recording
    # rather than hiding under "not applicable": varonly rewrites the NAME LIST, the two placebos
    # and the two jobstrip arms edit somewhere else entirely. The heading they carry is the
    # baseline's, byte for byte.
    "ledger-origorder-varonly.yaml": "no quantifier edit",
    "ledger-ownplacebo.yaml": "no quantifier edit",
    "ledger-belowline-placebo.yaml": "no quantifier edit",
    "ledger-jobstrip.yaml": "no quantifier edit",
    "ledger-jobstrip-placebo.yaml": "no quantifier edit",
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


def axis_of(spec: str) -> str:
    """Declared construction axis, cross-checked against the arm's own rendered purpose.

    ⚠️ THE DERIVATION IS IMPORTED, NOT REIMPLEMENTED. `_mkvariant_construction_axis.family_of` is
    the function that decides what the specs ARE when they are built; if the tally carried its own
    copy of the rule, the two could drift and the table would be classifying arms by a definition
    that no longer builds them. This campaign has already published one table whose classifier was
    a re-typed copy of another one.
    """
    declared = AXIS.get(spec)
    if declared is None:
        raise _arm_table.Refuse(
            f"{spec}: no declared construction axis — add it to AXIS. The regex would happily "
            f"classify it, and a construction nobody decided on is how one arm becomes a family")
    p = HERE / "specs" / spec
    if not p.is_file():
        raise _arm_table.Refuse(f"{spec}: no such spec, cannot verify its axis")
    import yaml
    purpose = ""
    for f in yaml.safe_load(p.read_text())["files"]:
        if f["path"] == "internal/models/models.go":
            purpose = f["purpose"]
    derived = _consaxis.family_of(purpose)
    if declared != derived:
        raise _arm_table.Refuse(
            f"{spec}: declared axis {declared!r} but its purpose derives as {derived!r} — the "
            f"declaration and the text disagree and neither wins by default")
    return declared


DROPPED = []   # ⚠️ module-level ONLY so main() can print what every series threw away


def rows_for(name, pid, prefix):
    rows = _arm_table.build(HERE, prefix, BASELINE, pid=pid)
    for d in getattr(rows, "dropped", ()):
        DROPPED.append((name, d["label"], d["spec"], d["verdict"]))
    for r in rows:
        spec = r["spec"]
        if spec not in LOCATION:
            raise _arm_table.Refuse(
                f"{name}/{r['label']}: spec {spec} has no declared location — add it to LOCATION "
                f"rather than letting it fall into a bucket by accident")
        r["series"], r["location"] = name, LOCATION[spec]
        r["family"] = family_of(spec)
        r["axis"] = axis_of(spec)
    return rows


def by_axis(rows):
    """(axis, size bucket) -> counts, ON-LINE treated arms only.

    ⚠️ THIS IS THE TABLE 15 AUGUST COULD NOT BUILD. Its split was "the adverb ladder" against
    "everything else", and everything else differed from the ladder in several ways at once. Here
    the two families are defined by ONE property of the same slot, so the rows that used to sit in
    "other rewrite" for four different reasons get separated by what they actually do.
    """
    out = {}
    for r in rows:
        if r["location"] != "on-line":
            continue
        d = int(r["delta"])
        bucket = "<=+14" if d <= 14 else (">=+20" if d >= 20 else "the gap (+15..+19)")
        c = out.setdefault((r["axis"], bucket), {"n": 0, "long": 0, "nonnull": 0, "arms": []})
        c["n"] += 1
        c["long"] += r["verdict"] == "LONG"
        c["nonnull"] += r["verdict"] != "ABSENT"
        c["arms"].append(f"{r['series']}/{r['label']} {r['delta']} {r['verdict'].split(':')[0]}")
    return out


def size_matched(rows, delta=20):
    """The arms at EXACTLY one size, split by axis — the only comparison free of the size term.

    Everything else in this file pools sizes inside a bucket, and a bucket that spans +20 to +51
    can always be accused of hiding a size effect inside it. At a single delta there is nothing
    left to hide: same size, same two regions, same names, different construction.
    """
    out = {}
    for r in rows:
        if r["location"] != "on-line" or int(r["delta"]) != delta:
            continue
        c = out.setdefault(r["axis"], {"n": 0, "long": 0, "nonnull": 0, "arms": []})
        c["n"] += 1
        c["long"] += r["verdict"] == "LONG"
        c["nonnull"] += r["verdict"] != "ABSENT"
        c["arms"].append(f"{r['series']}/{r['label']} {r['spec']} {r['verdict'].split(':')[0]}")
    return out


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

    print(f"  pooled over {len(SERIES)} screened processes, {len(rows)} ledger rows")
    # ⚠️ PRINTED EVERY RUN, not only when it is convenient. A draw the GPU killed counts nowhere,
    # and a table that silently omits it looks exactly like a table where it never happened.
    for series, label, spec, verdict in DROPPED:
        print(f"    dropped: {series}/{label} ({spec}) {verdict} — classifies nothing")
    print()
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

    print(f"\n    {'construction AXIS':<26} {'size':<20} {'n':>3}  "
          f"{'reached LONG':>13}  {'above ABSENT':>13}")
    y = by_axis(rows)
    for key in sorted(y, key=lambda k: (k[0], k[1])):
        c = y[key]
        print(f"    {key[0]:<26} {key[1]:<20} {c['n']:>3}  "
              f"{c['long']:>6} of {c['n']:<4}  {c['nonnull']:>6} of {c['n']:<4}")
        if a.verbose:
            for arm in c["arms"]:
                print(f"        {arm}")

    z = size_matched(rows, 20)
    print(f"\n    SIZE-MATCHED at exactly +20 — the comparison with no size term left in it")
    if not z:
        print("      (no on-line arms at +20 in the series listed above)")
    for key in sorted(z):
        c = z[key]
        print(f"    {key:<26} {'+20 exactly':<20} {c['n']:>3}  "
              f"{c['long']:>6} of {c['n']:<4}  {c['nonnull']:>6} of {c['n']:<4}")
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

    # 6. THE AXIS. Same contract as FAMILY — declared AND derived, disagreement is fatal — and the
    #    same trap it fell into once: the arms that must NOT be swept in are checked by name.
    chk("the adverb rung derives as a pad", axis_of("ledger-linefloor-4.yaml"), "quantifier pad")
    chk("the NEW non-adverbial arm derives as a pad",
        axis_of("ledger-consaxis-pad1.yaml"), "quantifier pad")
    chk("the paraphrase derives as a replacement",
        axis_of("ledger-sentinelline-placebo.yaml"), "quantifier replacement")
    chk("the NEW second replacement derives as one",
        axis_of("ledger-consaxis-rep1.yaml"), "quantifier replacement")
    # ⚠️ L5 IS THE ROW THAT WOULD FALSIFY THE PAD HYPOTHESIS IF IT WERE IN THE FAMILY. It retains
    # "all" and pads it, it is +13, and it is LONG on p1. It is out because it moves a third
    # region, and that exclusion is pinned here so it cannot be quietly relaxed later.
    chk("L5 (pads 'all' but ALSO rewrites the tail) is NOT a pad arm",
        axis_of("ledger-linedose-5.yaml"), "not a quantifier-slot arm")
    chk("L3 (noun phrase only) is neither pad nor replacement",
        axis_of("ledger-linedose-3.yaml"), "no quantifier edit")
    chk("L2 (+8, 'all of them', tail intact) IS a pad arm — the pad family predates today",
        axis_of("ledger-linedose-2.yaml"), "quantifier pad")
    chk("the shipped rewrite is off this axis entirely",
        axis_of("ledger-origorder.yaml"), "not a quantifier-slot arm")

    try:
        axis_of("ledger-tagfix.yaml")
        ok = False
        print("  FAIL a spec with no declared axis did NOT stop the tally")
    except _arm_table.Refuse:
        print("  ok   a spec with no declared axis stops the tally")

    AXIS["ledger-linefloor-4.yaml"] = "quantifier replacement"
    try:
        axis_of("ledger-linefloor-4.yaml")
        ok = False
        print("  FAIL a declared/derived AXIS disagreement did NOT stop the tally")
    except _arm_table.Refuse:
        print("  ok   a declared/derived AXIS disagreement stops the tally")
    finally:
        AXIS["ledger-linefloor-4.yaml"] = "quantifier pad"

    # ⚠️ EVERY SPEC THE TALLY CAN COUNT NEEDS BOTH DECLARATIONS, checked here rather than in the
    # middle of a live series: LOCATION was added mid-session once and refused on a drawn arm.
    for spec in LOCATION:
        chk(f"{spec} has a declared axis too", spec in AXIS, True)

    ax = by_axis([
        {"series": "x", "label": "a", "delta": "+20", "verdict": "LONG",
         "location": "on-line", "axis": "quantifier replacement"},
        {"series": "x", "label": "b", "delta": "+20", "verdict": "ABSENT",
         "location": "on-line", "axis": "quantifier pad"},
        {"series": "x", "label": "c", "delta": "+20", "verdict": "LONG",
         "location": "off-line", "axis": "quantifier pad"},
    ])
    chk("the axis table splits one size bucket two ways",
        (ax[("quantifier replacement", ">=+20")]["long"], ax[("quantifier pad", ">=+20")]["long"]),
        (1, 0))
    chk("the axis table excludes off-line arms", sum(c["n"] for c in ax.values()), 2)

    sm = size_matched([
        {"series": "x", "label": "a", "spec": "s", "delta": "+20", "verdict": "LONG",
         "location": "on-line", "axis": "quantifier replacement"},
        {"series": "x", "label": "b", "spec": "s", "delta": "+21", "verdict": "LONG",
         "location": "on-line", "axis": "quantifier replacement"},
        {"series": "x", "label": "c", "spec": "s", "delta": "+20", "verdict": "ABBREVIATED:E",
         "location": "on-line", "axis": "quantifier pad"},
    ], 20)
    chk("the size-matched table takes ONLY the exact delta",
        (sm["quantifier replacement"]["n"], sm["quantifier pad"]["n"]), (1, 1))
    chk("and it keeps ABBREVIATED out of the LONG column",
        (sm["quantifier pad"]["long"], sm["quantifier pad"]["nonnull"]), (0, 1))

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
