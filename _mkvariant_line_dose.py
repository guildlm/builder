#!/usr/bin/env python3
"""A dose ladder on the declaration line: how SMALL an edit still flips the file?

    ./_mkvariant_line_dose.py            # writes specs/ledger-linedose-{1,2}.yaml
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
         matchable" -> "Sentinel errors, all of them matchable".  +9 characters.

    L1 FLIPS  -> the line is hypersensitive: being DIFFERENT is the whole treatment, at any size,
                 while its neighbours ignore fifty times as much text. The shipped rule would be
                 even further from the mechanism than 10 August's correction already says.
    L1 NULL   -> there is a THRESHOLD between −1 and +20, and L2 bisects it.

⚠️ THE LIST OF NAMES IS BYTE-IDENTICAL IN BOTH ARMS. Only the clause introducing it changes, so
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

    d1 = len(folded(texts["1"])) - len(fb)
    d2 = len(folded(texts["2"])) - len(fb)
    chk(f"L1 delta {d1:+d} is smaller in magnitude than every flipping arm so far (min 20)",
        abs(d1) < 20, True)
    chk(f"L2 delta {d2:+d} lies strictly between L1 and the +20 paraphrase", d1 < d2 < 20, True)
    chk("the two arms differ from each other", texts["1"] == texts["2"], False)

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else build())
