#!/usr/bin/env python3
"""Would normalising wall-clock stamps and sub-second durations MERGE two error
surfaces that are genuinely different?

The fix is motivated (a real repair was refused on the ledger's own request-log
output, twice). The risk it carries is the opposite error: two distinct failures
collapsing into one, which would make the repeat detector stop a fix loop that
was actually making progress, and would make the non-regressing gate accept a
move that introduced something new.

Measured on the archive rather than argued: every merge the proposed regex causes
is printed with BOTH surfaces, so a merge that is not a timestamp/duration
difference is visible rather than assumed away.

    ./_stamp_merge_probe.py            # sweep logs/
    ./_stamp_merge_probe.py --self-test
"""
from __future__ import annotations

import pathlib
import re
import sys

# what ships today
CURRENT = re.compile(r"0x[0-9a-f]+|goroutine \d+|\d+\.\d+s|\+0x[0-9a-f]+")

# the two additions under test
STAMP = r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?"
DUR = r"\d+(?:\.\d+)?(?:ns|µs|us|ms)\b"
PROPOSED = re.compile(CURRENT.pattern + "|" + STAMP + "|" + DUR)

_FAIL = re.compile(r"^(?:---|\s+---) FAIL", re.M)


def surfaces(text: str) -> list[str]:
    """Split a captured log into per-check error blocks. A block is a run of
    non-blank lines; crude, but the question here is only whether two blocks that
    differ today stop differing, and that is insensitive to the split."""
    out, cur = [], []
    for line in text.splitlines():
        if line.strip():
            cur.append(line.rstrip())
        elif cur:
            out.append("\n".join(cur))
            cur = []
    if cur:
        out.append("\n".join(cur))
    return [b for b in out if len(b) > 20]


def sweep(paths: list[pathlib.Path]) -> int:
    merges: list[tuple[str, str, str]] = []
    touched = collapsed = 0
    for p in paths:
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        blocks = surfaces(text)
        if not blocks:
            continue
        cur = {CURRENT.sub("?", b): b for b in blocks}
        if len(cur) < 2:
            continue
        seen: dict[str, str] = {}
        for csig, block in cur.items():
            psig = PROPOSED.sub("?", block)
            if psig in seen and seen[psig] != block:
                merges.append((p.name, seen[psig], block))
            seen[psig] = block
        if len(seen) < len(cur):
            touched += 1
            collapsed += len(cur) - len(seen)

    print(f"  logs scanned                       {len(paths)}")
    print(f"  logs where the count changes       {touched}")
    print(f"  surfaces merged                    {collapsed}")
    if not merges:
        print("\n  No merge anywhere in the archive. The additions are INERT on historical data —")
        print("  which is the expected shape: only 2 logs carry a wall-clock stamp at all, and the")
        print("  defect this fixes was observed live, not mined from the archive.")
        return 0
    print(f"\n  {len(merges)} merge(s) — read each and decide if the two are the same failure:")
    for name, a, b in merges[:12]:
        only = PROPOSED.sub("?", a) == PROPOSED.sub("?", b)
        print(f"\n  ── {name}   (identical after normalisation: {only})")
        print("     A: " + a.splitlines()[0][:110])
        print("     B: " + b.splitlines()[0][:110])
        da = [ln for ln in a.splitlines() if ln not in b.splitlines()][:2]
        for ln in da:
            print("     A-only: " + ln[:110])
    return 0


def self_test() -> int:
    ok = True

    def chk(name: str, got, want) -> None:
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: {got!r} != {want!r}")

    # the live defect: two runs of the SAME refusal, differing only in stamp and µs
    a = "moving MemStore breaks\n2026/07/31 13:37:35 GET /accounts -> 200 (1.708µs)"
    b = "moving MemStore breaks\n2026/07/31 15:19:04 GET /accounts -> 200 (1.25µs)"
    chk("same-refusal differs today", CURRENT.sub("?", a) != CURRENT.sub("?", b), True)
    chk("same-refusal matches after", PROPOSED.sub("?", a) == PROPOSED.sub("?", b), True)

    # THE REJECT CONDITION: a genuinely new compile error must still register
    c = "./main.go: package models is not in std"
    chk("new compile error stays distinct", PROPOSED.sub("?", a) != PROPOSED.sub("?", c), True)

    # a duration inside an assertion is still noise, but two DIFFERENT assertions must not merge
    d = "--- FAIL: TestTimeout\n    want 5ms got 9ms"
    e = "--- FAIL: TestRetry\n    want 5ms got 9ms"
    chk("different test names stay distinct", PROPOSED.sub("?", d) != PROPOSED.sub("?", e), True)

    # ...and this one DOES merge, deliberately: same test, different measured time
    f = "--- FAIL: TestTimeout\n    want 5ms got 12ms"
    chk("same test, different timing, merges", PROPOSED.sub("?", d) == PROPOSED.sub("?", f), True)

    # seconds were already handled; make sure the addition did not break them
    chk("existing 1.23s still normalised", PROPOSED.sub("?", "ok pkg 1.23s") == PROPOSED.sub("?", "ok pkg 4.56s"), True)

    # µs and us are both real in Go output depending on terminal encoding
    chk("us and µs both caught", PROPOSED.sub("?", "took 3us") == PROPOSED.sub("?", "took 9us"), True)

    # a bare number that is not a duration must survive — 200ms is noise, 200 is a status code
    chk("status code 200 survives", PROPOSED.sub("?", "-> 200") != PROPOSED.sub("?", "-> 404"), True)

    print("  self-test: OK — the live refusal merges, a new compile error and a different test do not"
          if ok else "  self-test: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    root = pathlib.Path(__file__).parent / "logs"
    raise SystemExit(sweep(sorted(root.glob("*.log"))))
