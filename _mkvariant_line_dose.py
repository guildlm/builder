#!/usr/bin/env python3
"""A dose ladder on the declaration line: how SMALL an edit still flips the file?

    ./_mkvariant_line_dose.py            # writes specs/ledger-linedose-{1,2,3}.yaml
    ./_mkvariant_line_dose.py --self-test

WHERE THIS COMES FROM. On pid 46375 four different edits to models.go's sentinel line all make
the declarer write the name it otherwise omits — the full treatment (+51), `var ErrX` alone
(+30), A+C with B withheld (+21) and a pure paraphrase that adds no information (+20). Meanwhile
+54 characters on the sentence directly ABOVE and +21 on the sentence directly BELOW do nothing.

Every flipping arm so far is at least +20 characters. Nothing smaller has ever been drawn, so
"any rewrite of the line" is a claim about a range that was never probed at its bottom.

    L1   ONE WORD, a synonym, meaning identical:  "matchable with errors.Is" -> "matchable via
         errors.Is".  −1 character. The smallest edit that is still an edit.
    L2   a light rephrase of the same clause, no information added:  "Sentinel errors, all
         matchable" -> "Sentinel errors, all of them matchable".  +8 characters.

    L1 FLIPS  -> the line is hypersensitive: being DIFFERENT is the whole treatment, at any size,
                 while its neighbours ignore fifty times as much text. The shipped rule would be
                 even further from the mechanism than 10 August's correction already says.
    L1 NULL   -> there is a THRESHOLD between −1 and +20, and L2 bisects it.

⚠️ THE LIST OF NAMES IS BYTE-IDENTICAL IN EVERY ARM. Only the clause introducing it changes, so
no arm can be explained by having touched a name, an order or a form.
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).parent
BASE = HERE / "specs" / "ledger-origorder-baseline.yaml"
TARGET = "internal/models/models.go"
NAMES = "ErrInvalid, ErrNotFound, ErrExists, ErrUnbalanced, ErrInsufficientFunds."

LADDER = {
    "1": ("      Sentinel errors, all matchable with errors.Is:\n",
          "      Sentinel errors, all matchable via errors.Is:\n"),
    "2": ("      Sentinel errors, all matchable with errors.Is:\n",
          "      Sentinel errors, all of them matchable with errors.Is:\n"),
    # L3 is not a smaller dose — it is a DIFFERENT PLACE, chosen after L1 and L2 came back null.
    # Laid side by side, the six arms drawn on this line split perfectly by WHAT they touch:
    #     FLIP  paraphrase "Sentinel errors"->"Sentinel error values" · A+C ->"Exported
    #           sentinels" · B only, noun phrase untouched but the NAMES backticked · full, both
    #     NULL  L1 "with"->"via" · L2 "all"->"all of them"   (connective words only)
    # So: touch the NOUN PHRASE naming the concept, or the NAMES, and it flips; touch the words
    # in between and it does not. L3 changes ONLY the noun phrase, by +6 — SMALLER than L2's +8
    # null, so a flip here eliminates size outright rather than arguing about it.
    "3": ("      Sentinel errors, all matchable with errors.Is:\n",
          "      Sentinel error values, all matchable with errors.Is:\n"),
    # L4 = L1 AND L3 TOGETHER, and it is the arm the whole ladder was building toward. L3 came
    # back null, killing the noun-phrase rule, and with it the last CONTENT account. What is left
    # fits all seven arms with no exceptions: they split by HOW MANY REGIONS of the line the edit
    # touches — 1 region null (−1, +6, +8), 2 or more regions flip (+20, +21, +30, +51).
    #
    # L4 touches TWO regions and costs +5 characters, LESS than every null in the ladder. If it
    # flips, size is finished as an explanation and the rule is a COUNT.
    #
    # ⚠️ And it is the same shape as process A's store result — three single removals null, the
    # triple flips — which is why it is worth drawing rather than admiring: two independent
    # injection points would then show the same non-additive threshold in the number of edits.
    "4": ("      Sentinel errors, all matchable with errors.Is:\n",
          "      Sentinel error values, all matchable via errors.Is:\n"),
    # L5 = L1 AND L2 AND L3, all three tiny edits at once. L4 turned the outcome out to be
    # ORDERED (ABSENT < ABBREVIATED < LONG) rather than binary, so the ladder now has a real
    # question: does the outcome climb with the NUMBER of edited regions or with the SIZE?
    #     2 regions, +5   -> ABBREVIATED
    #     2 regions, +20  -> LONG
    #     3 regions, +13  -> ?     LONG means COUNT buys distance that size alone has not;
    #                              ABBREVIATED means the climb is mostly size.
    "5": ("      Sentinel errors, all matchable with errors.Is:\n",
          "      Sentinel error values, all of them matchable via errors.Is:\n"),
    # L6 SEPARATES COUNT FROM SIZE, which every arm so far confounds. L5 reached LONG with THREE
    # regions at +13; L4 reached only ABBREVIATED with TWO at +5. L6 is TWO regions at +14 — the
    # same size as L5, one region fewer:
    #     LONG        -> size explains the climb; the third region in L5 was not doing the work.
    #     ABBREVIATED -> the COUNT of edited regions matters on its own, at equal size.
    "6": ("      Sentinel errors, all matchable with errors.Is:\n",
          "      Sentinel error values, all readily matchable with errors.Is:\n"),
}


def folded(text: str, path: str = TARGET) -> str:
    import yaml

    for f in yaml.safe_load(text)["files"]:
        if f["path"] == path:
            return f["purpose"]
    raise KeyError(path)


def build_text(key: str) -> str:
    base = BASE.read_text()
    old, new = LADDER[key]
    n = base.count(old)
    if n != 1:
        raise SystemExit(f"REFUSING: the sentinel heading occurs {n} times, expected 1")
    return base.replace(old, new)


def build() -> int:
    base = BASE.read_text()
    for key in LADDER:
        out = build_text(key)
        p = HERE / "specs" / f"ledger-linedose-{key}.yaml"
        p.write_text(out)
        print(f"  wrote {p.name:<30} folded delta {len(folded(out)) - len(folded(base)):+d}")
    print("    (for reference: paraphrase +20, A+C +21, `var ErrX` +30, full treatment +51,")
    print("     and the NULL arms are +54 one sentence above and +21 one sentence below)")
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
    import re

    tok = lambda t: sorted(re.findall(r"\bErr[A-Z][A-Za-z0-9]*\b", t))  # noqa: E731

    texts = {}
    for key in LADDER:
        out = build_text(key)
        texts[key] = out
        fo = folded(out)
        chk(f"L{key}: the name list is byte-identical", NAMES in fo, True)
        # ⚠️ The intent is "the heading changed", and the first version of this check encoded a
        # per-arm expectation of which fragment SURVIVES — which was simply wrong for L2 ("all
        # of them matchable with" does not contain "all matchable with") and failed a correct
        # arm. State the intent instead: the original heading is gone in both.
        chk(f"L{key}: the original heading is gone",
            "Sentinel errors, all matchable with errors.Is" in fo, False)
        chk(f"L{key}: no sentinel added or dropped", tok(out), tok(base))
        chk(f"L{key}: carries none of the known treatments",
            ("xported" in fo, "`var Err" in fo, "errors.New" in fo), (False, False, False))
        chk(f"L{key}: errors.Is is still promised", "errors.Is" in fo, True)

        import yaml

        pb = {f["path"]: f["purpose"] for f in yaml.safe_load(base)["files"]}
        po = {f["path"]: f["purpose"] for f in yaml.safe_load(out)["files"]}
        chk(f"L{key}: exactly one purpose differs", [p for p in pb if pb[p] != po[p]], [TARGET])

    d = {k: len(folded(v)) - len(fb) for k, v in texts.items()}
    chk(f"L1 delta {d['1']:+d} is smaller in magnitude than every flipping arm so far (min 20)",
        abs(d['1']) < 20, True)
    chk(f"L2 delta {d['2']:+d} lies strictly between L1 and the +20 paraphrase",
        d['1'] < d['2'] < 20, True)
    # ⚠️ L3 MUST BE SMALLER THAN THE L2 NULL, or it cannot eliminate size
    chk(f"L3 delta {d['3']:+d} is SMALLER than the L2 null ({d['2']:+d})", d['3'] < d['2'], True)
    chk("L3 changes the noun phrase", "Sentinel error values" in folded(texts['3']), True)
    chk("L3 leaves the connective words alone",
        "all matchable with errors.Is" in folded(texts['3']), True)
    chk("all arms differ from each other", len(set(texts.values())), len(LADDER))
    # ⚠️ L4 must be the EXACT conjunction of two arms that were individually null, and cheaper
    # than either — otherwise it is a new arm rather than a test of the count rule.
    f4 = folded(texts['4'])
    chk("L4 carries L3's change", "Sentinel error values" in f4, True)
    chk("L4 carries L1's change", "matchable via errors.Is" in f4, True)
    # ⚠️ CORRECTED CLAIM. The first version asserted L4 was smaller than EVERY null and failed:
    # L1 is −1, a SHRINK, so a signed minimum makes "smaller" meaningless across the sign. The
    # claim that actually does the work is against the two nulls that ADD text.
    chk(f"L4 delta {d['4']:+d} adds less text than BOTH positive nulls "
        f"(L2 {d['2']:+d}, L3 {d['3']:+d})", d['4'] < min(d['2'], d['3']), True)
    f5 = folded(texts['5'])
    chk("L5 carries all three single edits",
        ("Sentinel error values" in f5, "all of them" in f5, "matchable via" in f5),
        (True, True, True))
    chk(f"L5 delta {d['5']:+d} sits strictly between the ABBREVIATED arm ({d['4']:+d}) "
        f"and the smallest LONG arm (+20)", d['4'] < d['5'] < 20, True)
    f6 = folded(texts['6'])
    chk("L6 edits exactly two regions: the noun phrase and the quantifier",
        ("Sentinel error values" in f6, "all readily matchable" in f6, "matchable via" in f6),
        (True, True, False))
    chk(f"L6 delta {d['6']:+d} is within 2 characters of L5's {d['5']:+d} — the point of the arm",
        abs(d['6'] - d['5']) <= 2, True)

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else build())
