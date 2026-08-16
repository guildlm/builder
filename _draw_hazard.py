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


BASE_SPEC = "ledger-origorder-baseline.yaml"
SCREEN_SPEC = "ledger-ownplacebo.yaml"


def session(rows: list) -> dict:
    """What a night's probing actually bought, per process. Counted, because I would miscount it.

    ⚠️ THE ONE NUMBER A READER WILL WANT — "how many eligible processes did you get?" — is the
    one most easily inflated by memory: a process that was ABSENT at baseline FEELS eligible, and
    it is not, because the screen is the second gate and it kills processes (2 of the 4 screens
    that ran to completion tonight flipped). Eligible means BOTH gates, and this counts them.
    """
    per = {}
    for r in rows:
        p = per.setdefault(r["pid"], {"base": "", "screen": "", "arms": [], "last": ""})
        if r["spec"] == BASE_SPEC and not p["base"]:
            p["base"] = r["verdict"]
        elif r["spec"] == SCREEN_SPEC and not p["screen"]:
            p["screen"] = r["verdict"]
        elif r["spec"] not in (BASE_SPEC, SCREEN_SPEC):
            p["arms"].append((r["label"], r["spec"], r["verdict"]))
        p["last"] = r["verdict"]

    out = {"probed": len(per), "informative": 0, "eligible": 0, "arms": 0, "arms_real": 0,
           "eligible_pids": [], "lost_on_screen_death": 0, "lost_to_screen_flip": 0}
    for pid, p in per.items():
        if p["base"] == "ABSENT":
            out["informative"] += 1
            if p["screen"] == "ABSENT":
                out["eligible"] += 1
                out["eligible_pids"].append((pid, len(p["arms"]),
                                             "died" if p["last"] in DEAD + AMBIGUOUS else "ok"))
            elif p["screen"] in DEAD + AMBIGUOUS:
                out["lost_on_screen_death"] += 1
            elif p["screen"]:
                out["lost_to_screen_flip"] += 1
        out["arms"] += len(p["arms"])
        # ⚠️ AN ARM THE GPU KILLED IS NOT AN ARM. Reported apart from the attempt count, because
        # "3 arms drawn" and "2 arms measured" are different sentences and only one is true.
        out["arms_real"] += sum(1 for _, _, v in p["arms"] if v not in DEAD + AMBIGUOUS)
    return out


def baseline_shas(root: pathlib.Path, rows: list) -> tuple:
    """(sha -> count, missing) over the ABSENT-at-baseline trees, ACROSS processes.

    ⚠️ THE ARM TABLE CANNOT ANSWER THIS and that is deliberate: it refuses on a series spanning
    two pids, because a series IS a process. "Is the untreated declaration byte-identical across
    DIFFERENT processes?" is the opposite question — it is only meaningful across pids — so it
    gets its own function rather than a weakening of that refusal.
    """
    import hashlib

    counts, missing = collections.Counter(), 0
    for r in rows:
        if r["spec"] != BASE_SPEC or r["verdict"] != "ABSENT":
            continue
        t = root / "generated" / f"probe-{r['label']}" / "internal" / "models" / "models.go"
        if not t.is_file():
            missing += 1
            continue
        counts[hashlib.sha256(t.read_bytes()).hexdigest()[:8]] += 1
    return counts, missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="")
    ap.add_argument("--session", action="store_true",
                    help="what the night's probing bought, per process")
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

    if a.session:
        s = session(rows)
        classifying = sum(1 for r in rows if r["verdict"] not in DEAD + AMBIGUOUS + OTHER_VOID)
        print(f"\n    processes probed                {s['probed']:>3}")
        print(f"    ABSENT at baseline (informative){s['informative']:>3}")
        print(f"      of those, lost when the SCREEN draw died   {s['lost_on_screen_death']:>3}")
        print(f"      of those, discarded because the SCREEN FLIPPED THEM "
              f"{s['lost_to_screen_flip']:>3}")
        print(f"    ELIGIBLE (both gates)           {s['eligible']:>3}")
        for pid, n, how in s["eligible_pids"]:
            print(f"      pid {pid:<8} arms drawn {n}   ended: {how}")
        print(f"    treated arms ATTEMPTED          {s['arms']:>3}")
        print(f"    treated arms that MEASURED one  {s['arms_real']:>3}")
        print(f"    rows that classify something    {classifying:>3} of {len(rows)}")
        counts, missing = baseline_shas(HERE, rows)
        tot = sum(counts.values())
        print(f"    ABSENT baselines on disk        {tot:>3}"
              + (f"  ({missing} tree(s) missing)" if missing else ""))
        for sha, n in counts.most_common():
            print(f"      {sha}  {n} of {tot}"
                  + ("   <- the archive's untreated declaration" if sha == "3a78b0d8" else ""))
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

    # ⚠️ ELIGIBILITY IS TWO GATES, and the count that matters is the one that is easiest to
    # inflate from memory. Four processes here: one passes both, one is ABSENT then its screen
    # DIES, one is ABSENT then its screen FLIPS it, one is LONG at baseline and never gets a
    # screen at all. Only the first is eligible.
    sess = (
        f"2026-08-17T01:00:00 pid=10 label=a spec={BASE_SPEC} VERDICT=ABSENT\n"
        f"2026-08-17T01:01:00 pid=10 label=b spec={SCREEN_SPEC} VERDICT=ABSENT\n"
        f"2026-08-17T01:02:00 pid=10 label=c spec=arm.yaml VERDICT=LONG\n"
        f"2026-08-17T01:03:00 pid=20 label=d spec={BASE_SPEC} VERDICT=ABSENT\n"
        f"2026-08-17T01:04:00 pid=20 label=e spec={SCREEN_SPEC} VERDICT=VOID-SERVER-DIED\n"
        f"2026-08-17T01:05:00 pid=30 label=f spec={BASE_SPEC} VERDICT=ABSENT\n"
        f"2026-08-17T01:06:00 pid=30 label=g spec={SCREEN_SPEC} VERDICT=LONG\n"
        f"2026-08-17T01:07:00 pid=40 label=h spec={BASE_SPEC} VERDICT=LONG\n")
    s = session(positioned(parse(sess)))
    chk("processes probed", s["probed"], 4)
    chk("informative = ABSENT at baseline", s["informative"], 3)
    chk("ELIGIBLE needs BOTH gates", s["eligible"], 1)
    chk("a screen that DIED is not a screen that passed", s["lost_on_screen_death"], 1)
    chk("a screen that FLIPPED the process is counted separately", s["lost_to_screen_flip"], 1)
    chk("arms are counted, and gates are not arms", s["arms"], 1)
    chk("a killed arm is attempted but not measured",
        (session(positioned(parse(sess + f"2026-08-17T01:08:00 pid=10 label=i spec=arm.yaml "
                                          f"VERDICT=VOID-SERVER-DIED\n")))["arms"],
         session(positioned(parse(sess + f"2026-08-17T01:08:00 pid=10 label=i spec=arm.yaml "
                                          f"VERDICT=VOID-SERVER-DIED\n")))["arms_real"]), (2, 1))
    chk("the eligible process is named with its arm count",
        s["eligible_pids"], [("10", 1, "ok")])

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        led = ""
        for label, body in (("x", "same"), ("y", "same"), ("z", "different"), ("w", "same")):
            d = root / "generated" / f"probe-{label}" / "internal" / "models"
            d.mkdir(parents=True)
            (d / "models.go").write_text(body)
            v = "ABSENT" if label != "w" else "LONG"
            led += f"2026-08-17T02:00:00 pid=9 label={label} spec={BASE_SPEC} VERDICT={v}\n"
        led += f"2026-08-17T02:01:00 pid=9 label=q spec={BASE_SPEC} VERDICT=ABSENT\n"  # no tree
        counts, missing = baseline_shas(root, parse(led))
        chk("only ABSENT baselines are hashed (LONG excluded)", sum(counts.values()), 3)
        chk("byte-identical trees collapse to one sha", max(counts.values()), 2)
        chk("a different tree is a different sha", len(counts), 2)
        chk("a missing tree is reported, not silently skipped", missing, 1)

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
