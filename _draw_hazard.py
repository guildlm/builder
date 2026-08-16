#!/usr/bin/env python3
"""How often does a draw DIE, and does it depend on where in a process's life it sits?

    ./_draw_hazard.py                 # whole ledger
    ./_draw_hazard.py --since 2026-08-16
    ./_draw_hazard.py --self-test

WHY THIS EXISTS. On 16 August the GPU watchdog started killing mlx_lm.server mid-draw and I wrote
a committed amendment saying the deaths were position-independent — "two processes died on their
FIRST draw, two on their second, one on its fourth" — off eleven rows I counted by eye. Four rows
later the split was 2 of 8 on first draws against 4 of 7 on later ones, which is the opposite
reading, and the amendment was already published. That is the ninth hand-counted number this
campaign has had to correct, and the standing rule it keeps re-learning is that a number in a log
is computed by an instrument with a self-test or it is not written.

WHAT A "DEATH" IS HERE. A row whose verdict classifies nothing:

    VOID-SERVER-DIED   the server was gone when the arm ended  (added 16 Aug; unambiguous)
    NO-FILE            the file never landed                   (⚠️ AMBIGUOUS BEFORE 16 AUG —
                       until that fix, a dead server was recorded as NO-FILE too, so old NO-FILE
                       rows are counted in a SEPARATE column rather than merged into deaths)

⚠️ POSITION AND SPEC ARE CONFOUNDED IN THIS CAMPAIGN AND THE TABLE SAYS SO RATHER THAN HIDING IT.
Every treated arm is drawn with RESTART=0 — that is what makes a pair a pair — so "not the first
draw on this process" and "not a baseline probe" are almost the same set of rows. The by-spec
table is printed next to the by-position one for exactly that reason; neither is a cause.
"""

import argparse
import collections
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent
LEDGER = HERE / "logs" / "PROBE-LEDGER.txt"
ROW = re.compile(
    r"^(?P<ts>\S+)\s+pid=(?P<pid>\S+)\s+label=(?P<label>\S+)\s+"
    r"spec=(?P<spec>\S+)\s+VERDICT=(?P<verdict>\S+)")

DEAD = ("VOID-SERVER-DIED",)
AMBIGUOUS = ("NO-FILE",)
OTHER_VOID = ("VOID-REPAIRED", "VOID-CLASSIFIER")


def parse(text: str, since: str = "") -> list:
    rows = []
    for line in text.splitlines():
        m = ROW.match(line)
        if not m:
            continue
        d = m.groupdict()
        if since and d["ts"] < since:
            continue
        rows.append(d)
    return rows


def positioned(rows: list) -> list:
    """Attach each row's 1-based position among the draws on ITS pid, in ledger order."""
    seen = collections.Counter()
    out = []
    for r in rows:
        seen[r["pid"]] += 1
        out.append({**r, "pos": seen[r["pid"]]})
    return out


def bucket(rows: list, key) -> dict:
    out = {}
    for r in rows:
        c = out.setdefault(key(r), {"n": 0, "dead": 0, "ambig": 0})
        c["n"] += 1
        c["dead"] += r["verdict"] in DEAD
        c["ambig"] += r["verdict"] in AMBIGUOUS
    return out


def render(title: str, table: dict) -> str:
    lines = [f"    {title:<28} {'draws':>6} {'died':>6} {'no-file':>8}  rate"]
    for k in sorted(table):
        c = table[k]
        rate = (c["dead"] + c["ambig"]) / c["n"] if c["n"] else 0
        lines.append(f"    {str(k):<28} {c['n']:>6} {c['dead']:>6} {c['ambig']:>8}  {rate:5.0%}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="")
    a = ap.parse_args()

    rows = positioned(parse(LEDGER.read_text(), a.since))
    if not rows:
        print("no rows")
        return 1
    print(f"  {len(rows)} ledger rows"
          + (f" since {a.since}" if a.since else " (whole ledger)")
          + f", {len({r['pid'] for r in rows})} processes\n")
    print(render("position on its process",
                 bucket(rows, lambda r: "1st draw (fresh restart)" if r["pos"] == 1
                        else f"draw {r['pos']} (RESTART=0)")))
    print()
    print(render("spec", bucket(rows, lambda r: r["spec"])))
    print()
    # ⚠️ THE COMPARISON THE AMENDMENT GOT WRONG, printed as one line so it cannot be re-eyeballed.
    first = bucket([r for r in rows if r["pos"] == 1], lambda r: "first")
    later = bucket([r for r in rows if r["pos"] > 1], lambda r: "later")
    f, l = first.get("first"), later.get("later")
    if f and l:
        fr = (f["dead"] + f["ambig"]) / f["n"]
        lr = (l["dead"] + l["ambig"]) / l["n"]
        print(f"    FIRST draws {f['dead']+f['ambig']} of {f['n']} lost ({fr:.0%})   ·   "
              f"LATER draws {l['dead']+l['ambig']} of {l['n']} lost ({lr:.0%})")
        print("    ⚠️ position and spec are confounded: every later draw is also a treated arm.")
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

    text = (
        "noise\n"
        "2026-08-16T01:00:00  pid=1  label=a spec=base.yaml VERDICT=ABSENT\n"
        "2026-08-16T01:10:00  pid=1  label=b spec=screen.yaml VERDICT=VOID-SERVER-DIED\n"
        "2026-08-16T01:20:00  pid=2  label=c spec=base.yaml VERDICT=VOID-SERVER-DIED\n"
        "2026-08-15T01:20:00  pid=3  label=d spec=base.yaml VERDICT=NO-FILE\n"
        "2026-08-16T01:30:00  pid=2  label=e spec=base.yaml VERDICT=LONG\n")
    rows = positioned(parse(text))
    chk("noise lines are not rows", len(rows), 5)
    chk("position counts per pid, in ledger order",
        [(r["pid"], r["pos"]) for r in rows], [("1", 1), ("1", 2), ("2", 1), ("3", 1), ("2", 2)])
    chk("--since filters by timestamp", len(parse(text, "2026-08-16")), 4)

    b = bucket(rows, lambda r: "all")["all"]
    chk("deaths and NO-FILE are counted SEPARATELY, not merged",
        (b["n"], b["dead"], b["ambig"]), (5, 2, 1))

    first = bucket([r for r in rows if r["pos"] == 1], lambda r: "f")["f"]
    later = bucket([r for r in rows if r["pos"] > 1], lambda r: "l")["l"]
    chk("first-draw rows are the fresh-restart ones", first["n"], 3)
    chk("later-draw rows are the RESTART=0 ones", later["n"], 2)
    chk("a death on a later draw lands in the later bucket", later["dead"], 1)

    txt = render("t", bucket(rows, lambda r: r["spec"]))
    chk("render splits by spec", "screen.yaml" in txt and "base.yaml" in txt, True)

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
