#!/usr/bin/env python3
"""Before publishing a finding, ask whether this directory already contains it.

    ./_prior_art.py logs/RESULT-something-new.txt      # what already covers this?
    ./_prior_art.py --sweep                            # every log vs every other
    ./_prior_art.py --self-test

WHY THIS EXISTS. Three times on 31 July I claimed novelty or correctness that one command would
have refuted:

    "identical prompt, different output across processes"   `ls logs/ | grep -i process` — the
        answer was already in this directory, from the day before, with a stronger design
    the as-drawn grader   _asdrawn_diff.py was written that MORNING to enforce exactly the
        distinction I then violated in a new tool four hours later
    the order channel     `grep -rl _package_context logs/` — PREDICTION-taskapipro.txt lists it
        under "PROVEN (measured, no model needed)"

Each time the correction ended with a note that the check costs one command. Writing that note down
three times did not make me run it. So it becomes a tool, the same way the segmentation invariants
did — a rule I have to remember is not a control.

WHAT IT IS NOT. This finds TEXTUAL prior art: files sharing distinctive terms. It cannot tell you
whether a claim is genuinely new — only where to look before deciding. A high score means READ THAT
FILE, not "you were scooped"; a zero means nothing shares your vocabulary, which is weaker evidence
of novelty than it feels like.
"""
from __future__ import annotations

import pathlib
import re
import sys

LOGS = pathlib.Path(__file__).parent / "logs"

# code-ish identifiers and multi-word capitals — the terms a claim actually turns on.
# Ordinary prose words are useless here: every file in this directory says "measured".
# ⚠️ TWO DEFECTS IN THE FIRST VERSION, both found by running it on the file it was built for:
#   {3,} between the capitals rejected MemStore — M-e-m-S leaves only TWO chars before the second
#   capital, so the very identifier this campaign turns on was invisible. Now {2,}.
#   And ALL-CAPS words matched: this directory writes emphasis in capitals constantly, so BEFORE,
#   MECHANISM, OUTPUT and COSTS dominated every result and the ranking was measuring shouting.
#   A real MixedCaps identifier contains a lowercase letter; that is the filter.
#   {2,} still rejected GoToolchain — "Go" leaves ONE char before the second capital. Now {1,}.
# ⚠️ AND THE BIGGEST TERM CLASS HERE IS NEITHER: it is FILENAMES. Measured on the file this tool
#   was built for — 12 dotted paths (internal/store/memory.go, specs/ledger.yaml) against 3
#   identifiers. A term extractor that only sees code names is blind to most of what these notes
#   are actually about. `.txt` is EXCLUDED deliberately: a draft naming logs/FINDING-x.txt is
#   CITING it, and a tool meant to find prior art you have not yet noticed must not score the
#   citations you already made.
_TERM = re.compile(
    r"\b(?:_[a-z][a-z0-9_]{3,}"
    r"|[a-z]+_[a-z_]{3,}"
    r"|[A-Z][a-zA-Z]{1,}[A-Z][a-zA-Z]*"
    r"|[\w/-]*\.(?:go|py|yaml|sh))\b"
)
_STOP = {
    "RESULT", "FINDING", "PREREG", "NOTE", "PREDICTION", "CORRECTED", "RETRACTED",
    "MEASURED", "WARNING", "GREEN", "EMPTY", "SPLIT", "CONSOLIDATED",
}


def terms(text: str) -> set[str]:
    return {t for t in _TERM.findall(text)
            if t not in _STOP and len(t) > 4 and any(c.islower() for c in t)}


def score(target: pathlib.Path, others: list[pathlib.Path]) -> list[tuple[float, int, str, set[str]]]:
    tt = terms(target.read_text(errors="replace"))
    if not tt:
        return []
    out = []
    for p in others:
        if p.resolve() == target.resolve():
            continue
        ot = terms(p.read_text(errors="replace"))
        shared = tt & ot
        if len(shared) < 3:
            continue
        # share of the TARGET's vocabulary that this file already uses
        out.append((len(shared) / len(tt), len(shared), p.name, shared))
    return sorted(out, reverse=True)


def report(target: pathlib.Path, limit: int = 6) -> int:
    others = sorted(LOGS.glob("*.txt"))
    rows = score(target, others)
    print(f"  target: {target.name}")
    print(f"  distinctive terms: {len(terms(target.read_text(errors='replace')))}")
    if not rows:
        print("\n  Nothing in logs/ shares 3+ distinctive terms with this.")
        print("  ⚠️ That is weak evidence of novelty — it means no file shares your VOCABULARY.")
        return 0
    print(f"\n  {'overlap':>8s} {'terms':>6s}  file")
    for frac, n, name, shared in rows[:limit]:
        print(f"  {frac:7.0%} {n:6d}  {name}")
        print(f"           {', '.join(sorted(shared)[:8])}")
    print("\n  READ the top file before claiming this is new. A high overlap is a pointer,")
    print("  not a verdict — and a low one is not a clearance.")
    return 0


def sweep(limit: int = 12) -> int:
    files = sorted(LOGS.glob("*.txt"))
    cache = {p: terms(p.read_text(errors="replace")) for p in files}
    pairs = []
    for i, a in enumerate(files):
        for b in files[i + 1:]:
            ta, tb = cache[a], cache[b]
            if not ta or not tb:
                continue
            shared = ta & tb
            if len(shared) < 8:
                continue
            frac = len(shared) / min(len(ta), len(tb))
            if frac >= 0.45:
                pairs.append((frac, len(shared), a.name, b.name))
    pairs.sort(reverse=True)
    print(f"  files compared        {len(files)}")
    print(f"  pairs sharing >=45% of the smaller file's vocabulary   {len(pairs)}")
    print("\n  closest pairs — each is a candidate for 'these two say the same thing':")
    for frac, n, a, b in pairs[:limit]:
        print(f"  {frac:5.0%} {n:4d}  {a}")
        print(f"              {b}")
    return 0


def self_test() -> int:
    ok = True

    def chk(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: {got!r} != {want!r}")

    t = terms("The _package_context call and MemStore and required_decls matter here.")
    chk("picks _underscore names", "_package_context" in t, True)
    chk("picks MixedCaps", "MemStore" in t, True)
    chk("picks snake_case", "required_decls" in t, True)
    chk("drops ordinary prose", "matter" in t, False)
    # the banner words appear in every file here and would match everything
    chk("drops the boilerplate headings", terms("RESULT FINDING MEASURED"), set())
    # ⚠️ this directory SHOUTS. Without the lowercase filter these dominated every ranking.
    chk("drops ALL-CAPS emphasis", terms("BEFORE MECHANISM OUTPUT COSTS CHANNEL"), set())
    chk("keeps a real MixedCaps identifier", terms("MemStore GoToolchain"), {"MemStore", "GoToolchain"})
    # the class this corpus actually uses most
    chk("keeps source filenames", "internal/store/memory.go" in terms("see internal/store/memory.go now"), True)
    chk("keeps spec filenames", "specs/ledger.yaml" in terms("in specs/ledger.yaml the order"), True)
    chk("drops .txt citations", terms("logs/FINDING-a-b-c.txt says"), set())

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        a = d / "a.txt"
        b = d / "b.txt"
        c = d / "c.txt"
        a.write_text("_package_context and MemStore and required_decls and _error_signature")
        b.write_text("we already proved _package_context, MemStore, required_decls, _error_signature")
        c.write_text("unrelated: _server_pid and GoToolchain and _canonical_error and _stub_files")
        rows = score(a, [b, c])
        chk("finds the file that shares the vocabulary", rows[0][2], "b.txt")
        chk("the unrelated file does not qualify", len(rows), 1)
        chk("a file does not match itself", [r for r in score(a, [a, b]) if r[2] == "a.txt"], [])

    print("  self-test: OK — identifiers extracted, boilerplate dropped, prior art ranked"
          if ok else "  self-test: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    if "--sweep" in sys.argv:
        raise SystemExit(sweep())
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(report(pathlib.Path(args[0])))
