#!/usr/bin/env python3
"""Turn ONE construction into an AXIS: four arms at the IDENTICAL +20, two families, same slot.

    ./_mkvariant_construction_axis.py              # writes specs/ledger-consaxis-{pad1,rep1}.yaml
    ./_mkvariant_construction_axis.py --self-test

WHERE THIS COMES FROM. 15 August split the archive by CONSTRUCTION and the size law dissolved:

    substantive rewrite (other)  >= +20    12 of 12 LONG
    quantifier ladder            >= +20     1 of 3
    quantifier ladder        +15..+19       2 of 9
    quantifier ladder            <= +14     0 of 6      (ladder 3 of 18 overall, ALL THREE on p4)

and the sharpest single row was F4 (+20, "all quite readily") coming back ABSENT twice on the
same process, in the same two regions, at the same +20, on which the paraphrase (+20, "every one
of them") is LONG. That is a size-matched null, which is what makes the comparison worth anything.

⚠️ THE LIMIT THAT LOG WROTE DOWN, AND THE REASON THIS FILE EXISTS. That result is ONE
construction against everything else. "The adverb ladder is inert" and "there is an axis along
which constructions differ" are not the same claim, and the archive cannot separate them, because
every non-ladder arm ever drawn also differs from the ladder in some other way (it is bigger, or
it names `var`, or it moves more regions). One inert family is an anecdote about a family. TWO
inert families that share a shape — and TWO flipping families that share the opposite shape — is
an axis.

THE SHAPE THIS PROPOSES, stated before the draw so it can fail. Take the declaration heading:

    Sentinel errors, all matchable with errors.Is: <five names>
                     ^^^ the quantifier slot

Every arm here rewrites region ONE (the noun phrase, +6, byte-identical to the ladder's) and the
quantifier slot, and touches NOTHING else — the tail "matchable with errors.Is:" and the name list
stay byte-identical. The slot is 17 characters in all four arms, so all four are +20.

    family              slot                  arm                       status
    pad (retain)        "all quite readily"   F4  ledger-linefloor-4    DRAWN: ABSENT x2 p5, LONG p4
    pad (retain)        "all of them below"   G1  ledger-consaxis-pad1  NEW
    replace             "every one of them"   paraphrase                DRAWN: LONG on 4 of 4
    replace             "each one of these"   R1  ledger-consaxis-rep1  NEW

PAD keeps the base quantifier "all" as the head and appends to it. REPLACE removes it. That is
the axis: not size (all four are +20), not region count (all four move two regions), not region
identity (the same two), not the names (byte-identical), not information (none of the four adds
any).

⚠️ WHAT THIS STILL CANNOT HOLD CONSTANT, and it is the same honest limit the ladder had: a
construction cannot be changed without changing words. The four slots are four different word
sequences. What is held is size, region count, region identity, the name list and the tail.

⚠️ ONE ARCHIVE ROW IS THE ENEMY OF THIS HYPOTHESIS AND IS NAMED HERE RATHER THAN DISCOVERED
LATER. L5 (ledger-linedose-5, +13) renders "Sentinel error values, all of them matchable VIA
errors.Is:" — it retains "all" and pads it non-adverbially, exactly like G1, and it is **LONG on
p1** (ABSENT on p2 and p3). It is excluded from the pad family here by SHAPE, not by preference:
it also rewrites the tail ("with" -> "via"), so it moves three regions, and every arm in this
table moves two. The self-test asserts that exclusion mechanically. If G1 comes back LONG, L5 is
the row that predicted it, and this file will have been wrong in the direction it was warned.
"""

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent
BASE = HERE / "specs" / "ledger-origorder-baseline.yaml"
TARGET = "internal/models/models.go"
NAMES = "ErrInvalid, ErrNotFound, ErrExists, ErrUnbalanced, ErrInsufficientFunds."

HEADING = "      Sentinel errors, all matchable with errors.Is:\n"
NOUN = ("Sentinel errors", "Sentinel error values")  # +6, byte-identical in EVERY arm below
BASE_QUANT = "all"

# The two NEW arms. Both slots are 17 characters, which is what makes them +20 — the same +20 as
# the two arms already drawn, whose slots are also 17 characters.
ARMS = {
    "pad1": ("all of them below", "quantifier pad", 20),
    "rep1": ("each one of these", "quantifier replacement", 20),
}

# The two arms ALREADY DRAWN that complete the 2x2. They are not rebuilt; they are checked.
DRAWN = {
    "F4  (pad, adverbial)": ("ledger-linefloor-4.yaml", "all quite readily",
                             "quantifier pad", 20),
    "paraphrase (replace)": ("ledger-sentinelline-placebo.yaml", "every one of them",
                             "quantifier replacement", 20),
}

# ⚠️ THE ARM THAT MUST **NOT** BE IN THE PAD FAMILY, checked mechanically. See the header.
EXCLUDED = ("ledger-linedose-5.yaml", "moves a THIRD region (with -> via); LONG on p1")

# ⚠️ DERIVED FROM THE RENDERED TEXT, NOT FROM THE FILE NAME. The tail and the colon are part of
# the signature: an arm that rewrites the tail is a different construction and must not match.
SLOT_RE = re.compile(r"Sentinel error(?:s| values), (?P<slot>.+?) matchable with errors\.Is:")


def folded(text: str, path: str = TARGET) -> str:
    import yaml

    for f in yaml.safe_load(text)["files"]:
        if f["path"] == path:
            return f["purpose"]
    raise KeyError(path)


def slot_of(purpose: str):
    """The quantifier slot, or None when the arm is not of this shape at all."""
    m = SLOT_RE.search(purpose)
    return m.group("slot") if m else None


def family_of(purpose: str) -> str:
    """PAD / REPLACE / neither, decided by the text the model actually receives.

    ⚠️ A SUBSTRING IS NOT A CONSTRUCTION — the lesson the tally learned on 15 August, when
    'Sentinel error values, all ' matched two arms that are not rungs. The head is compared as a
    TOKEN ('all' followed by a space) and the slot must be strictly longer than the base
    quantifier, so the bare-noun-phrase arm (slot still exactly 'all') falls in neither family.
    """
    slot = slot_of(purpose)
    if slot is None:
        return "not a quantifier-slot arm"
    if slot == BASE_QUANT:
        return "no quantifier edit"
    if slot.startswith(BASE_QUANT + " "):
        return "quantifier pad"
    return "quantifier replacement"


def heading_for(key: str) -> str:
    slot, _, _ = ARMS[key]
    return f"      {NOUN[1]}, {slot} matchable with errors.Is:\n"


def build_text(key: str) -> str:
    base = BASE.read_text()
    n = base.count(HEADING)
    if n != 1:
        raise SystemExit(f"REFUSING: the sentinel heading occurs {n} times, expected 1")
    return base.replace(HEADING, heading_for(key))


def build() -> int:
    base = BASE.read_text()
    fb = folded(base)
    for key, (slot, fam, want) in ARMS.items():
        out = build_text(key)
        p = HERE / "specs" / f"ledger-consaxis-{key}.yaml"
        p.write_text(out)
        d = len(folded(out)) - len(fb)
        flag = "" if d == want else f"   ⚠️ INTENDED {want:+d}"
        print(f"  wrote {p.name:<30} {d:+d}  slot {slot!r:<20} {fam}{flag}")
    print("    the two arms already drawn that complete the 2x2, recomputed from their specs:")
    for label, (name, slot, fam, want) in DRAWN.items():
        p = HERE / "specs" / name
        if p.is_file():
            fo = folded(p.read_text())
            d = len(fo) - len(fb)
            print(f"      {label:<22} {d:+d}  slot {slot_of(fo)!r:<20} {family_of(fo)}"
                  + ("" if d == want else f"   ⚠️ expected {want:+d}"))
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

    import yaml

    base = BASE.read_text()
    fb = folded(base)
    pb = {f["path"]: f["purpose"] for f in yaml.safe_load(base)["files"]}
    tok = lambda t: sorted(re.findall(r"\bErr[A-Z][A-Za-z0-9]*\b", t))  # noqa: E731

    # the base itself must sit in neither family, or the derivation is not measuring an EDIT
    chk("the baseline is 'no quantifier edit'", family_of(fb), "no quantifier edit")
    chk("the baseline's slot is the bare quantifier", slot_of(fb), BASE_QUANT)

    texts, folds = {}, {}
    for key, (slot, fam, want) in ARMS.items():
        out = build_text(key)
        texts[key], fo = out, folded(build_text(key))
        folds[key] = fo

        chk(f"{key}: delta is exactly the intended {want:+d}", len(fo) - len(fb), want)
        chk(f"{key}: the slot is 17 characters, like both drawn arms", len(slot), 17)
        chk(f"{key}: the rendered slot is the one intended", slot_of(fo), slot)
        chk(f"{key}: the family DERIVES as declared", family_of(fo), fam)
        chk(f"{key}: the name list is byte-identical", NAMES in fo, True)
        chk(f"{key}: no sentinel added or dropped", tok(out), tok(base))
        chk(f"{key}: region 1 is the ladder's noun phrase", f"{NOUN[1]}," in fo, True)
        chk(f"{key}: the tail is byte-identical",
            "matchable with errors.Is: " + NAMES in fo, True)
        chk(f"{key}: the original heading is gone",
            "Sentinel errors, all matchable with errors.Is" in fo, False)
        chk(f"{key}: carries none of the known treatments",
            ("xported" in fo, "`var Err" in fo, "errors.New" in fo), (False, False, False))
        po = {f["path"]: f["purpose"] for f in yaml.safe_load(out)["files"]}
        chk(f"{key}: paths and order unchanged", list(pb), list(po))
        chk(f"{key}: exactly one purpose differs", [p for p in pb if pb[p] != po[p]], [TARGET])

        # ⚠️ REGION COUNT IS THE THING BEING HELD FIXED, so restore the base FROM the arm and
        # demand byte equality: two substitutions and nothing else may separate them.
        h = heading_for(key)
        chk(f"{key}: the heading differs from the base in exactly the 2 intended regions",
            (h.replace(NOUN[1], NOUN[0]).replace(slot, BASE_QUANT), h == HEADING),
            (HEADING, False))

    # ---- the 2x2 itself: four arms, one size, two families -------------------------------
    sizes, fams, slots = {}, {}, {}
    for key in ARMS:
        sizes[key] = len(folds[key]) - len(fb)
        fams[key] = family_of(folds[key])
        slots[key] = slot_of(folds[key])
    for label, (name, slot, fam, want) in DRAWN.items():
        p = HERE / "specs" / name
        if not p.is_file():
            ok = False
            print(f"  FAIL {label}: {name} is missing — the 2x2 has nothing to be measured against")
            continue
        fo = folded(p.read_text())
        sizes[label], fams[label], slots[label] = len(fo) - len(fb), family_of(fo), slot_of(fo)
        chk(f"{label}: still measures {want:+d}", sizes[label], want)
        chk(f"{label}: its slot is still {slot!r}", slots[label], slot)
        chk(f"{label}: derives as {fam}", fams[label], fam)
        chk(f"{label}: region 1 is the same noun phrase", f"{NOUN[1]}," in fo, True)
        chk(f"{label}: the tail is byte-identical", "matchable with errors.Is: " + NAMES in fo, True)

    chk("all four arms are the SAME size", len(set(sizes.values())), 1)
    chk("all four slots are 17 characters", {len(s) for s in slots.values()}, {17})
    chk("all four arms have DIFFERENT slots", len(set(slots.values())), 4)
    chk("the families split the four arms 2 and 2",
        sorted(fams.values()),
        ["quantifier pad", "quantifier pad",
         "quantifier replacement", "quantifier replacement"])

    # ---- the exclusion, checked rather than asserted in prose ----------------------------
    p = HERE / "specs" / EXCLUDED[0]
    if p.is_file():
        fo = folded(p.read_text())
        chk(f"{EXCLUDED[0]} is NOT swept into the pad family ({EXCLUDED[1]})",
            family_of(fo), "not a quantifier-slot arm")
        chk(f"{EXCLUDED[0]} does retain 'all ' — i.e. the exclusion is by SHAPE, not by luck",
            "all of them" in fo, True)
    else:
        ok = False
        print(f"  FAIL {EXCLUDED[0]} is missing — the exclusion cannot be checked")

    # the bare-noun-phrase arm and the tail-only arm must also fall outside both families
    for name, want in (("ledger-linedose-3.yaml", "no quantifier edit"),        # +6, slot = "all"
                       ("ledger-linedose-1.yaml", "not a quantifier-slot arm"),  # -1, tail only
                       ("ledger-linedose-4.yaml", "not a quantifier-slot arm"),  # +5, the unstable
                       ("ledger-origorder.yaml", "not a quantifier-slot arm"),   # +51, shipped
                       ("ledger-origorder-ac.yaml", "not a quantifier-slot arm")):
        q = HERE / "specs" / name
        if q.is_file():
            chk(f"{name} derives as {want}", family_of(folded(q.read_text())), want)

    # every rung of the adverb ladder must land in the pad family, or the axis is not an axis
    for name in ("ledger-linedose-6.yaml", "ledger-linefloor-1.yaml", "ledger-linefloor-2.yaml",
                 "ledger-linefloor-3.yaml", "ledger-linefloor-4.yaml", "ledger-linedose-2.yaml"):
        q = HERE / "specs" / name
        if q.is_file():
            chk(f"{name} derives as a pad", family_of(folded(q.read_text())), "quantifier pad")

    # and the new arms must not accidentally reproduce something already drawn
    for key in ARMS:
        for name in sorted(pathlib.Path(HERE / "specs").glob("ledger-*.yaml")):
            if name.name.startswith("ledger-consaxis-"):
                continue
            try:
                other = folded(name.read_text())
            except KeyError:
                continue
            chk(f"{key} is not a duplicate of {name.name}", folds[key] == other, False)

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else build())
