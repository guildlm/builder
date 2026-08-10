#!/usr/bin/env python3
"""Build the placebo the 6 August sentinel experiment never had.

    ./_mkvariant_ownpurpose_placebo.py            # writes specs/ledger-ownplacebo.yaml
    ./_mkvariant_ownpurpose_placebo.py --self-test

WHY. 6 August concluded that showing the declaration form (`var ErrX`) in models.go's purpose is
what repairs ErrInsufficientFunds, and that the other two edits in the bundle are decoration
(386f2f8). Its arms were base / base2 / treated / treated2 / varonly — and NOT ONE of them edits
that purpose by a comparable amount WITHOUT the sentinel change.

10 August showed why that matters. Process 71409 flips models.go from 3a78b0d8 to ef8c15d6 for a
placebo that names no sentinel at all — on such a process every arm of the 6 August design comes
out exactly as it did, and "the declaration form repairs it" is indistinguishable from "editing
that purpose at all flips this process". One of the two processes probed that day was of this
type, so the confound is common, not exotic.

THE PLACEBO. models.go's own purpose, edited by about the same number of characters as the
treatment (+51 folded), in the same STYLE — it adds backticks around identifiers and a short
parenthetical, which is what the treatment does — while naming NO sentinel and leaving the
sentinel line untouched byte for byte.

USE IT AS A SCREEN, NOT AS AN ARM. A process that flips on this cannot discriminate and must be
discarded like a LONG baseline is discarded, and recorded in PROBE-LEDGER.txt. Only a process
that is INFORMATIVE and PLACEBO-NULL may host the treated arm.
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).parent
BASE = HERE / "specs" / "ledger-origorder-baseline.yaml"
TREATED = HERE / "specs" / "ledger-origorder.yaml"
OUT = HERE / "specs" / "ledger-ownplacebo.yaml"
TARGET = "internal/models/models.go"

EDITS = [
    (
        "      `Account{ID string, Name string}`, with JSON tags.\n",
        "      `Account{ID string, Name string}`, with JSON tags on both fields.\n",
    ),
    (
        "      `Posting{AccountID string, Amount money.Money}` — a POSITIVE amount adds\n"
        "      to that account, a NEGATIVE amount subtracts from it.\n",
        "      `Posting{AccountID string, Amount money.Money}` — a POSITIVE `Amount`\n"
        "      adds to that account, a NEGATIVE `Amount` subtracts from it.\n",
    ),
    (
        "      `Transaction{ID string, Memo string, Postings []Posting}`.\n",
        "      `Transaction{ID string, Memo string, Postings []Posting}` (each\n"
        "      `Posting` names one account).\n",
    ),
]


def apply_once(text: str, edits: list[tuple[str, str]]) -> str:
    for old, new in edits:
        n = text.count(old)
        if n != 1:
            raise SystemExit(f"REFUSING: pattern occurs {n} times, expected 1:\n{old}")
        text = text.replace(old, new)
    return text


def folded(text: str, path: str = TARGET) -> str:
    import yaml

    for f in yaml.safe_load(text)["files"]:
        if f["path"] == path:
            return f["purpose"]
    raise KeyError(path)


def build() -> int:
    base = BASE.read_text()
    out = apply_once(base, EDITS)
    OUT.write_text(out)
    d_pl = len(folded(out)) - len(folded(base))
    d_tr = len(folded(TREATED.read_text())) - len(folded(base))
    print(f"  wrote {OUT.name}")
    print(f"  folded purpose: baseline {len(folded(base))} · placebo {d_pl:+d} · "
          f"treatment {d_tr:+d} · mismatch {abs(d_pl - d_tr)} chars")
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
    out = apply_once(base, EDITS)

    import re

    tok = lambda t: sorted(re.findall(r"\bErr[A-Z][A-Za-z0-9]*\b", t))  # noqa: E731
    chk("the placebo names no new sentinel", tok(out), tok(base))
    chk("every sentinel keeps its exact count",
        {n: out.count(n) for n in set(tok(base))},
        {n: base.count(n) for n in set(tok(base))})

    # the sentinel line itself must be untouched, byte for byte
    line = ("Sentinel errors, all matchable with errors.Is: ErrInvalid, ErrNotFound, "
            "ErrExists, ErrUnbalanced, ErrInsufficientFunds.")
    chk("the sentinel line survives the placebo verbatim", line in folded(out), True)

    # ONLY models.go's purpose may differ
    import yaml

    fb = {f["path"]: f["purpose"] for f in yaml.safe_load(base)["files"]}
    fo = {f["path"]: f["purpose"] for f in yaml.safe_load(out)["files"]}
    chk("paths and order are unchanged", list(fb), list(fo))
    chk("exactly one purpose differs",
        [p for p in fb if fb[p] != fo[p]], [TARGET])

    # size match against the real treatment, which is the whole point of a placebo
    d_pl = len(folded(out)) - len(folded(base))
    d_tr = len(folded(TREATED.read_text())) - len(folded(base))
    chk(f"placebo delta {d_pl:+d} is within 10 chars of the treatment's {d_tr:+d}",
        abs(d_pl - d_tr) <= 10, True)

    for bad, why in ((EDITS[0][1], "text that is not in the baseline"),):
        try:
            apply_once(base, [(bad, "x")])
            chk(f"refuses {why}", False, True)
        except SystemExit:
            chk(f"refuses {why}", True, True)

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else build())
