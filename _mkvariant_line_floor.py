#!/usr/bin/env python3
"""Bisect the SIZE FLOOR between +14 and +20, with the region count held FIXED at two.

    ./_mkvariant_line_floor.py            # writes specs/ledger-linefloor-{1,2,3,4}.yaml
    ./_mkvariant_line_floor.py --self-test

WHERE THIS COMES FROM. Pooled over three screened processes, the on-line arms split almost
perfectly by SIZE and nothing else has survived as an account:

    on-line, >= +20   flips (reaches LONG somewhere)   8 of 8
    on-line, <= +14   flips                            2 of 14

but that split was never pre-registered, it is pooled ACROSS processes (whose wording->outcome
maps demonstrably differ), and it is CONFOUNDED: the big arms also touch more of the line. The
gap between +14 and +20 has never been drawn at all.

Two arms already bracket the gap at the SAME region count, which is what makes a clean bisection
possible at all:

    L6          +14   noun phrase +6  ·  "all" -> "all readily"        ABSENT on p1, p2, p3
    paraphrase  +20   noun phrase +6  ·  "all" -> "every one of them"  LONG on p1 and p3

Both edit exactly TWO regions of the heading. The only thing that separates them is how much the
second region grows. So this ladder holds region ONE byte-identical to those two arms (+6,
"Sentinel error values") and grows region TWO alone:

    F1  "all" -> "all reliably"        +15
    F2  "all" -> "all so readily"      +17
    F3  "all" -> "all very readily"    +19
    F4  "all" -> "all quite readily"   +20    <- SIZE-MATCHED to the paraphrase

F4 is the arm that can kill the size account outright rather than refining it. It is exactly the
size of the paraphrase, in the same two regions, built out of the same construction as F1-F3. If
+20 is a floor, F4 is LONG. If F4 is null while the paraphrase at the identical +20 is LONG on
the same process, then size is NOT the axis and something about the particular words comes back
into play at a resolution the campaign has not reached.

⚠️ WHAT THIS CANNOT HOLD CONSTANT, stated because it is the honest limit of the design: size
cannot be varied without changing characters, so the ADVERB differs between rungs (reliably / so
readily / very readily / quite readily). Construction, region count, region identity, and the
byte-identical name list are held; the adverb is not, and cannot be.

⚠️ THE ANCHORS MUST BE REDRAWN ON THE HOSTING PROCESS. The 8-of-8 / 2-of-14 tally is POOLED, and
10 August established that the wording->outcome map is process-specific. A floor located against
another process's anchors would be measuring the process, not the size.
"""

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent
BASE = HERE / "specs" / "ledger-origorder-baseline.yaml"
TARGET = "internal/models/models.go"
NAMES = "ErrInvalid, ErrNotFound, ErrExists, ErrUnbalanced, ErrInsufficientFunds."

HEADING = "      Sentinel errors, all matchable with errors.Is:\n"
NOUN = ("Sentinel errors", "Sentinel error values")  # +6, byte-identical in EVERY rung

# quantifier region only; the number after each is the intended TOTAL folded delta (+6 + this)
QUANT = {
    "1": ("all reliably", 15),
    "2": ("all so readily", 17),
    "3": ("all very readily", 19),
    "4": ("all quite readily", 20),
}

# the two arms this ladder bisects between, for reporting and for the self-test's bracket check
ANCHORS = {"L6 (+14, ABSENT x3)": ("ledger-linedose-6.yaml", 14),
           "paraphrase (+20, LONG on p1,p3)": ("ledger-sentinelline-placebo.yaml", 20)}


def folded(text: str, path: str = TARGET) -> str:
    import yaml

    for f in yaml.safe_load(text)["files"]:
        if f["path"] == path:
            return f["purpose"]
    raise KeyError(path)


def heading_for(key: str) -> str:
    quant, _ = QUANT[key]
    return f"      {NOUN[1]}, {quant} matchable with errors.Is:\n"


def build_text(key: str) -> str:
    base = BASE.read_text()
    n = base.count(HEADING)
    if n != 1:
        raise SystemExit(f"REFUSING: the sentinel heading occurs {n} times, expected 1")
    return base.replace(HEADING, heading_for(key))


def build() -> int:
    base = BASE.read_text()
    fb = folded(base)
    for key in QUANT:
        out = build_text(key)
        p = HERE / "specs" / f"ledger-linefloor-{key}.yaml"
        p.write_text(out)
        d = len(folded(out)) - len(fb)
        want = QUANT[key][1]
        flag = "" if d == want else f"   ⚠️ INTENDED {want:+d}"
        print(f"  wrote {p.name:<30} folded delta {d:+d}{flag}")
    print("    anchors that bracket this ladder, recomputed from their own specs:")
    for label, (name, want) in ANCHORS.items():
        p = HERE / "specs" / name
        if p.is_file():
            d = len(folded(p.read_text())) - len(fb)
            print(f"      {label:<32} {d:+d}" + ("" if d == want else f"   ⚠️ expected {want:+d}"))
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

    base = BASE.read_text()
    fb = folded(base)
    tok = lambda t: sorted(re.findall(r"\bErr[A-Z][A-Za-z0-9]*\b", t))  # noqa: E731

    import yaml

    pb = {f["path"]: f["purpose"] for f in yaml.safe_load(base)["files"]}

    texts, deltas = {}, {}
    for key in QUANT:
        out = build_text(key)
        texts[key] = out
        fo = folded(out)
        deltas[key] = len(fo) - len(fb)

        chk(f"F{key}: delta is exactly the intended {QUANT[key][1]:+d}", deltas[key], QUANT[key][1])
        chk(f"F{key}: the name list is byte-identical", NAMES in fo, True)
        chk(f"F{key}: no sentinel added or dropped", tok(out), tok(base))
        chk(f"F{key}: the original heading is gone",
            "Sentinel errors, all matchable with errors.Is" in fo, False)
        # ⚠️ region ONE must be byte-identical to L6's and the paraphrase's, not merely similar
        chk(f"F{key}: region 1 is the SAME noun phrase L6 uses", f"{NOUN[1]}," in fo, True)
        chk(f"F{key}: region 2 keeps the base quantifier and only extends it",
            f"{QUANT[key][0]} matchable with errors.Is" in fo, True)
        chk(f"F{key}: carries none of the known treatments",
            ("xported" in fo, "`var Err" in fo, "errors.New" in fo), (False, False, False))
        chk(f"F{key}: errors.Is is still promised", "errors.Is" in fo, True)
        po = {f["path"]: f["purpose"] for f in yaml.safe_load(out)["files"]}
        chk(f"F{key}: paths and order unchanged", list(pb), list(po))
        chk(f"F{key}: exactly one purpose differs", [p for p in pb if pb[p] != po[p]], [TARGET])

    chk("all four rungs differ from each other", len(set(texts.values())), len(QUANT))
    chk("the deltas are strictly increasing F1<F2<F3",
        deltas["1"] < deltas["2"] < deltas["3"], True)

    # ⚠️ THE WHOLE POINT: every rung must land INSIDE the unprobed gap (14, 20], and F4 must be
    # EQUAL to the paraphrase rather than merely near it, or it tests something weaker.
    for key in QUANT:
        chk(f"F{key} lands inside the unprobed gap (14 < d <= 20)", 14 < deltas[key] <= 20, True)

    for label, (name, want) in ANCHORS.items():
        p = HERE / "specs" / name
        if not p.is_file():
            ok = False
            print(f"  FAIL anchor {name} is missing — the ladder has nothing to bracket against")
            continue
        d = len(folded(p.read_text())) - len(fb)
        chk(f"anchor {label} still measures {want:+d}", d, want)

    chk("F4 is EXACTLY the paraphrase's size",
        deltas["4"], len(folded((HERE / "specs" / ANCHORS["paraphrase (+20, LONG on p1,p3)"][0])
                               .read_text())) - len(fb))

    # ⚠️ region COUNT is the thing being held fixed, so count it rather than believing the prose.
    # Both regions differ from the base in every rung, and NOTHING else in the heading does.
    for key in QUANT:
        h = heading_for(key)
        chk(f"F{key}: the heading differs from the base in exactly the 2 intended regions",
            (h.replace(NOUN[1], NOUN[0]).replace(QUANT[key][0], "all"), h == HEADING),
            (HEADING, False))

    # and the rungs must NOT accidentally reproduce an arm that has already been drawn
    for key in QUANT:
        fo = folded(texts[key])
        for name in ("ledger-linedose-6.yaml", "ledger-sentinelline-placebo.yaml",
                     "ledger-origorder.yaml", "ledger-origorder-ac.yaml"):
            p = HERE / "specs" / name
            if p.is_file():
                chk(f"F{key} is not a duplicate of {name}", fo == folded(p.read_text()), False)

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else build())
