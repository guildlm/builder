#!/usr/bin/env python3
"""The control at the right resolution: paraphrase the sentinel LINE, add nothing.

    ./_mkvariant_sentinel_line_placebo.py            # writes specs/ledger-sentinelline-placebo.yaml
    ./_mkvariant_sentinel_line_placebo.py --self-test

WHY THIS EXISTS. On the one process that passed the screen (46375), THREE different edits to
models.go's sentinel line all flip the file to declare the missing name:

    full bundle  +51   Exported sentinels + `var ErrX` forms + (each errors.New)
    B only       +30   `var ErrX` forms
    A+C          +21   Exported sentinels + (each errors.New), names left BARE

while a content-free edit of +54 characters to OTHER sentences in the same purpose does nothing.
Three treatments with almost nothing in common, one null that is larger than all of them.

That pattern has an obvious reading the campaign has not tested: the effective ingredient is not
any of A, B or C but TOUCHING THAT LINE AT ALL. This arm is the only thing that separates them —
a pure paraphrase of the sentinel line that adds no information: no "exported", no declaration
form, no errors.New, and the name list byte-identical.

    IF IT FLIPS   the shipped rule ("show the declaration form") describes the wrong ingredient.
                  What matters would be that the line was rewritten, not what it was rewritten to.
    IF IT DOES NOT the three treatments share something this paraphrase lacks, and the effect is
                  content after all — which is what every arm so far has assumed.

⚠️ The 29 July lesson applies exactly: a null is a claim about the instrument's RESOLUTION. The
screen placebo edited the same PURPOSE; this one edits the same LINE. Same experiment, one notch
finer, and the earlier null cannot answer this question.
"""

import pathlib
import sys

HERE = pathlib.Path(__file__).parent
BASE = HERE / "specs" / "ledger-origorder-baseline.yaml"
OUT = HERE / "specs" / "ledger-sentinelline-placebo.yaml"
TARGET = "internal/models/models.go"
NAMES = "ErrInvalid, ErrNotFound, ErrExists, ErrUnbalanced, ErrInsufficientFunds"

EDIT = (
    "      Sentinel errors, all matchable with errors.Is:\n",
    "      Sentinel error values, every one of them matchable with errors.Is:\n",
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
        raise SystemExit(f"REFUSING: the sentinel heading occurs {n} times, expected 1")
    return base.replace(old, new)


def build() -> int:
    base = BASE.read_text()
    out = build_text()
    OUT.write_text(out)
    print(f"  wrote {OUT.name}   folded delta {len(folded(out)) - len(folded(base)):+d}")
    for label, name in (("full treatment", "ledger-origorder.yaml"),
                        ("B only", "ledger-origorder-varonly.yaml"),
                        ("A+C", "ledger-origorder-ac.yaml"),
                        ("screen placebo (other sentences)", "ledger-ownplacebo.yaml")):
        p = HERE / "specs" / name
        if p.is_file():
            print(f"    vs {label:<34} {len(folded(p.read_text())) - len(folded(base)):+d}")
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

    chk("the line WAS rewritten", "Sentinel errors, all matchable" in fo, False)
    # ⚠️ each of the three known treatments must be absent, checked one by one rather than
    # by a single glance at the string — this arm's whole value is that it carries NONE of them
    chk("carries no A: 'exported' does not appear", "xported" in fo, False)
    chk("carries no B: no backticked var form", "`var Err" in fo, False)
    chk("carries no C: no errors.New parenthetical", "errors.New" in fo, False)
    chk("the name list is byte-identical", NAMES in fo, True)
    chk("errors.Is is still promised", "matchable with errors.Is" in fo, True)

    import re

    tok = lambda t: sorted(re.findall(r"\bErr[A-Z][A-Za-z0-9]*\b", t))  # noqa: E731
    chk("no sentinel added or dropped", tok(out), tok(base))

    import yaml

    pb = {f["path"]: f["purpose"] for f in yaml.safe_load(base)["files"]}
    po = {f["path"]: f["purpose"] for f in yaml.safe_load(out)["files"]}
    chk("paths and order unchanged", list(pb), list(po))
    chk("exactly one purpose differs", [p for p in pb if pb[p] != po[p]], [TARGET])
    chk("distinct from the baseline", fo == fb, False)

    d = len(fo) - len(fb)
    chk(f"delta {d:+d} is smaller than the screen placebo that did nothing (+54)", d < 54, True)

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else build())
