#!/usr/bin/env python3
"""Build the A+C arm — the one combination the 6 August unbundling never drew.

    ./_mkvariant_sentinel_ac.py            # writes specs/ledger-origorder-ac.yaml
    ./_mkvariant_sentinel_ac.py --self-test

The 6 August treatment bundled three edits to models.go's sentinel line:
    A  "Sentinel errors"  ->  "Exported sentinels"
    B  bare names         ->  backticked `var ErrX` forms
    C  + " (each errors.New)"
and showed B ALONE reproduces the full treatment byte for byte, so A and C add nothing ON TOP OF
B. That is sufficiency. It is not necessity, and the log said so at the time: A+C together was
never drawn, so "B is what does the work" has always had an untested alternative — that A or C
would also do it alone, and B merely got there first.

This is A+C with B withheld: the heading changes, the parenthetical is added, and the names stay
BARE. If it flips, B is not necessary and 6 August's shippable rule ("show the declaration form")
is the wrong summary of the treatment. If it does not, B's necessity is supported for the first
time.
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).parent
BASE = HERE / "specs" / "ledger-origorder-baseline.yaml"
OUT = HERE / "specs" / "ledger-origorder-ac.yaml"
TARGET = "internal/models/models.go"

EDIT = (
    "      Sentinel errors, all matchable with errors.Is:\n"
    "      ErrInvalid, ErrNotFound, ErrExists, ErrUnbalanced, ErrInsufficientFunds.\n",
    "      Exported sentinels, all matchable with errors.Is:\n"
    "      ErrInvalid, ErrNotFound, ErrExists, ErrUnbalanced, ErrInsufficientFunds\n"
    "      (each errors.New).\n",
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
        raise SystemExit(f"REFUSING: the sentinel line occurs {n} times, expected 1")
    return base.replace(old, new)


def build() -> int:
    base = BASE.read_text()
    out = build_text()
    OUT.write_text(out)
    d = len(folded(out)) - len(folded(base))
    others = {"full treatment": "ledger-origorder.yaml", "B only": "ledger-origorder-varonly.yaml",
              "screen placebo": "ledger-ownplacebo.yaml"}
    print(f"  wrote {OUT.name}   folded delta {d:+d}")
    for label, name in others.items():
        p = HERE / "specs" / name
        if p.is_file():
            print(f"    vs {label:<16} {len(folded(p.read_text())) - len(folded(base)):+d}")
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
    out = build_text()
    fb, fo = folded(base), folded(out)

    chk("A applied: the heading changed", "Exported sentinels" in fo, True)
    chk("A applied: the old heading is gone", "Sentinel errors" in fo, False)
    chk("C applied: the parenthetical is there", "(each errors.New)" in fo, True)
    # ⚠️ B WITHHELD is the entire point of this arm, so it gets two checks from both directions
    chk("B withheld: no backticked var form anywhere", "`var Err" in fo, False)
    chk("B withheld: the bare list survives verbatim",
        "ErrInvalid, ErrNotFound, ErrExists, ErrUnbalanced, ErrInsufficientFunds" in fo, True)

    import re

    tok = lambda t: sorted(re.findall(r"\bErr[A-Z][A-Za-z0-9]*\b", t))  # noqa: E731
    chk("no sentinel added or dropped", tok(out), tok(base))

    import yaml

    pb = {f["path"]: f["purpose"] for f in yaml.safe_load(base)["files"]}
    po = {f["path"]: f["purpose"] for f in yaml.safe_load(out)["files"]}
    chk("paths and order unchanged", list(pb), list(po))
    chk("exactly one purpose differs", [p for p in pb if pb[p] != po[p]], [TARGET])

    # it must be a DIFFERENT arm from the two that already exist, or it answers nothing
    for name in ("ledger-origorder.yaml", "ledger-origorder-varonly.yaml"):
        p = HERE / "specs" / name
        if p.is_file():
            chk(f"distinct from {name}", fo == folded(p.read_text()), False)
    chk("and distinct from the baseline", fo == fb, False)

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else build())
