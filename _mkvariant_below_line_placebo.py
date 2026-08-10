#!/usr/bin/env python3
"""Paraphrase the line BELOW the sentinel list — the one that mentions a sentinel but declares none.

    ./_mkvariant_below_line_placebo.py            # writes specs/ledger-belowline-placebo.yaml
    ./_mkvariant_below_line_placebo.py --self-test

TWO RULES SURVIVE EVERYTHING DRAWN SO FAR, and they have never been separated:

    (i)  editing the line that DECLARES the sentinel list flips the file
    (ii) editing ANY line that MENTIONS a sentinel flips the file

Every null so far — the screen placebo's three edits, including the sentence directly ABOVE the
list — touched sentences that name NO sentinel. Every flip touched the list itself. So (i) and
(ii) predict the same thing for every arm drawn to date.

This arm paraphrases the sentence directly BELOW the list: the `Validate` clause, which MENTIONS
ErrInvalid but declares nothing. Content preserved, ErrInvalid untouched, the declaration list
byte-identical.

    FLIPS    -> rule (ii): it is about lines that name a sentinel, not about the declaration.
    NULL     -> rule (i): the declaration line is special, and mentioning a sentinel is not
                enough. It would also make the radius directional — null above AND below, at a
                distance of one sentence in each direction.
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).parent
BASE = HERE / "specs" / "ledger-origorder-baseline.yaml"
OUT = HERE / "specs" / "ledger-belowline-placebo.yaml"
TARGET = "internal/models/models.go"
LIST_LINE = ("Sentinel errors, all matchable with errors.Is: ErrInvalid, ErrNotFound, "
             "ErrExists, ErrUnbalanced, ErrInsufficientFunds.")

EDIT = (
    "      `func (a Account) Validate() error` returns an error wrapping ErrInvalid\n"
    "      (fmt.Errorf with %w) when strings.TrimSpace(a.ID) is empty or\n"
    "      strings.TrimSpace(a.Name) is empty.",
    "      `func (a Account) Validate() error` returns an error that wraps ErrInvalid\n"
    "      (via fmt.Errorf with %w) whenever strings.TrimSpace(a.ID) is empty or\n"
    "      strings.TrimSpace(a.Name) is the empty string.",
)


def folded(text: str, path: str = TARGET) -> str:
    import yaml

    for f in yaml.safe_load(text)["files"]:
        if f["path"] == path:
            return f["purpose"]
    raise KeyError(path)


def build_text() -> str:
    base = BASE.read_text()
    old, new = EDIT
    n = base.count(old)
    if n != 1:
        raise SystemExit(f"REFUSING: the Validate clause occurs {n} times, expected 1")
    return base.replace(old, new)


def build() -> int:
    base = BASE.read_text()
    out = build_text()
    OUT.write_text(out)
    print(f"  wrote {OUT.name}   folded delta {len(folded(out)) - len(folded(base)):+d}")
    for label, name in (("line placebo (the list itself)", "ledger-sentinelline-placebo.yaml"),
                        ("A+C", "ledger-origorder-ac.yaml"),
                        ("screen placebo (above)", "ledger-ownplacebo.yaml")):
        p = HERE / "specs" / name
        if p.is_file():
            print(f"    vs {label:<32} {len(folded(p.read_text())) - len(folded(base)):+d}")
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

    base, out = BASE.read_text(), build_text()
    fb, fo = folded(base), folded(out)

    # ⚠️ THE DECLARATION LINE MUST SURVIVE VERBATIM — it is the thing this arm does NOT touch,
    # and the whole discrimination collapses if a single byte of it moves.
    chk("the declaration list is byte-identical", LIST_LINE in fo, True)
    # ⚠️ SCOPED TO THE ACCOUNT CLAUSE. "returns an error wrapping ErrInvalid" appears TWICE in
    # this purpose — once for Account.Validate and once for Transaction.Validate — so the broad
    # version of this check FAILED against a correct edit. The arm edits ONE clause on purpose;
    # the assertion has to say which.
    chk("the Account clause DID change",
        "`func (a Account) Validate() error` returns an error wrapping ErrInvalid" in fo, False)
    chk("ErrInvalid is still named in that clause",
        "`func (a Account) Validate() error` returns an error that wraps ErrInvalid" in fo, True)
    chk("the Transaction clause is untouched",
        "`func (t Transaction) Validate() error` returns an error wrapping" in fo, True)

    import re

    tok = lambda t: sorted(re.findall(r"\bErr[A-Z][A-Za-z0-9]*\b", t))  # noqa: E731
    chk("no sentinel added or dropped anywhere", tok(out), tok(base))
    chk("each sentinel keeps its exact count",
        {n: fo.count(n) for n in set(tok(fb))}, {n: fb.count(n) for n in set(tok(fb))})
    chk("carries none of the three treatments",
        ("xported" in fo, "`var Err" in fo, "errors.New" in fo), (False, False, False))

    import yaml

    pb = {f["path"]: f["purpose"] for f in yaml.safe_load(base)["files"]}
    po = {f["path"]: f["purpose"] for f in yaml.safe_load(out)["files"]}
    chk("paths and order unchanged", list(pb), list(po))
    chk("exactly one purpose differs", [p for p in pb if pb[p] != po[p]], [TARGET])

    d = len(fo) - len(fb)
    chk(f"delta {d:+d} is in the range where the list-line arms flipped (+20..+51)",
        20 <= d <= 51, True)

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else build())
