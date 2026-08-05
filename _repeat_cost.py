#!/usr/bin/env python3
"""How many fix rounds does this harness spend on an error surface it has ALREADY SEEN?

    ./_repeat_cost.py            # sweep logs/
    ./_repeat_cost.py --self-test

WHY THE QUESTION IS OPEN. The extension guard stops the loop when a surface repeats, but only
past the flat budget:

    if rnd > max_fix_rounds and sig in seen_surfaces: break

Inside the budget a repeat is LOGGED and deliberately not acted on, so the corpus stays measured
under one behaviour. That was the right call when it was made. It has a cost, and the cost has
never been counted with the CURRENT signature.

⚠️ A COUNT ALREADY EXISTS AND THIS IS NOT A RE-RUN OF IT. builder.py records: "27 in-budget
repeats were counted on 29 July with zero recoveries — but that count used a DIFFERENT signature:
the set of error lines, not this whole-output fingerprint. The two share a name and a purpose and
are not the same object." This tool uses the whole-output fingerprint, WITH the 31 July timestamp
normalisation, which is a third instrument again. The numbers are not comparable to either
earlier figure and the report says so rather than implying continuity.

WHAT A ROUND AFTER A REPEAT IS NOT. It is not automatically waste. The loop can fix a file, get
the same surface back because a DIFFERENT file has the same error, and then converge. So this
reports rounds-after-first-repeat and, separately, whether the build ever went green afterwards —
which is the only thing that distinguishes a wasted round from a slow one.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

_ROUND = "compile/test FAILED"
_ERRLINE = "]     ! "
# ⚠️ THE OBVIOUS REGEX IS WRONG IN BOTH DIRECTIONS, measured 31 July.
#   r"green" matches FIX 1's own warning, "build never went green" — so a build that never
#   converged reads as green. A false POSITIVE produced by this repo's newest log line.
#   And searching only the last line misses it entirely: a green build's final line is
#   "Generated <x> into <path>", with "converged to green after fix round N" two lines above.
# The builder prints exactly one success marker. Match that, and nothing else.
_GREEN = re.compile(r"^\[guildlm-build\] converged to green", re.M)


# ⚠️ A LOG FILE IS NOT A BUILD. Measured 31 July, AFTER this tool's first result was published:
# 40 of 617 log files hold more than one build. iso-shortener-07170020.log holds FOUR, each with
# its own "converged to green" and one failed round apiece — and reading the file as one build
# turned that into a single build repeating the same surface four times, which is the exact
# opposite of what happened. It was caught because a build reported four failed rounds AND
# "converged to green after fix round 1", a contradiction that only a merged log can produce.
# ⚠️ A LOG FILE IS NOT A BUILD. Segmentation lives in _logseg.py — one definition, because
# two disagreeing segmenters is exactly how the 654-vs-853 discrepancy happened.
from _logseg import builds_of  # noqa: E402


def rounds_of(text: str) -> list[str]:
    """Per-round error output, reconstructed from the `!`-prefixed lines the builder logs."""
    out, cur = [], None
    for line in text.splitlines():
        if _ROUND in line:
            cur = []
            out.append(cur)
        elif cur is not None and _ERRLINE in line:
            cur.append(line.split(_ERRLINE, 1)[1])
        elif cur is not None and "] " in line and _ERRLINE not in line and cur:
            cur = None
    return ["\n".join(r) for r in out if r]


def analyse(text: str, sig) -> dict | None:
    rs = rounds_of(text)
    if len(rs) < 2:
        return None
    sigs = [sig(r) for r in rs]
    seen: set[str] = set()
    first_repeat = None
    for i, s in enumerate(sigs, 1):
        if s in seen and first_repeat is None:
            first_repeat = i
        seen.add(s)
    return {
        "rounds": len(rs),
        "distinct": len(set(sigs)),
        "first_repeat": first_repeat,
        "after_repeat": (len(rs) - first_repeat) if first_repeat else 0,
        # a repeat INSIDE the budget is the case the policy chose not to act on
        "in_budget": bool(first_repeat and first_repeat <= 5),
        "green": bool(_GREEN.search(text)),
        "sigs": sigs,
    }


# ⚠️ CONSECUTIVE IS NOT THE SAME PREDICATE AS `first_repeat` ABOVE, AND THE DIFFERENCE IS THE
# WHOLE POINT OF THE PROPOSED POLICY. `first_repeat` is set-based: A B A B repeats at round 3.
# The policy under consideration stops only on a RUN — A B A B never fires, because alternating
# surfaces mean the fixer is still moving the build, just in a circle it might yet escape. A
# set-based stop would kill those; a run-based stop leaves them alone. The self-test pins exactly
# that case, because it is the one an eyeballed table would silently get wrong.
def k_fire(sigs: list[str], k: int) -> int | None:
    """1-based round at which the k-th CONSECUTIVE identical surface is observed, else None."""
    if k < 2:
        raise ValueError("k must be >= 2; k=1 would fire on the first failure of every build")
    run = 1
    for i in range(1, len(sigs)):
        run = run + 1 if sigs[i] == sigs[i - 1] else 1
        if run == k:
            return i + 1
    return None


def ksweep(rows: list[dict], ks=(2, 3, 4, 5)) -> None:
    """What a 'stop after K consecutive identical surfaces' rule would have done to the archive.

    STOPPING CAN ONLY SHORTEN A BUILD, NEVER REDIRECT IT — the rounds it removes are rounds that
    were actually run and observed, so no counterfactual generation is being imagined here. The
    one thing it CAN destroy is a green that arrived after the rule would have fired, and that is
    the column the decision rests on.

    ⚠️ A GREEN IS COUNTED AS KILLED IF THE RULE FIRES AT ALL, including on the very last recorded
    round. A green build with n error rounds converges on the fix APPLIED AFTER round n; firing at
    round n means that fix is never applied. Counting only i < n would understate the damage, so
    this takes the conservative side.
    """
    print("  IF THE HARNESS HAD STOPPED AFTER K CONSECUTIVE IDENTICAL SURFACES:")
    print(f"    {'K':>3}  {'builds fired':>12}  {'rounds saved':>12}  {'greens killed':>13}")
    for k in ks:
        fired = saved = killed = 0
        for r in rows:
            at = k_fire(r["sigs"], k)
            if at is None:
                continue
            fired += 1
            saved += r["rounds"] - at
            if r["green"]:
                killed += 1
        flag = "   <- FREE" if killed == 0 and saved else ""
        print(f"    {k:>3}  {fired:>12}  {saved:>12}  {killed:>13}{flag}")


def sweep(paths: list[pathlib.Path]) -> int:
    import builder as B

    rows = []
    segments = 0
    for p in paths:
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        segs = builds_of(text)
        segments += len(segs)
        for i, seg in enumerate(segs):
            r = analyse(seg, B._error_signature)
            if r:
                r["name"] = p.name if len(segs) == 1 else f"{p.name}#{i + 1}"
                rows.append(r)
    print(f"  log files {len(paths)} -> build segments {segments}")

    multi = len(rows)
    rep = [r for r in rows if r["first_repeat"]]
    inb = [r for r in rep if r["in_budget"]]
    wasted = sum(r["after_repeat"] for r in rep)
    green_after = [r for r in rep if r["green"]]

    print(f"  logs with 2+ fix rounds (the denominator)      {multi}")
    print(f"  ...that ever repeat a surface                  {len(rep)}")
    print(f"  ...whose FIRST repeat lands inside the budget  {len(inb)}   <- the policy's cases")
    print(f"  rounds spent after a first repeat, total       {wasted}")
    if rep:
        print(f"  median rounds after first repeat               {sorted(r['after_repeat'] for r in rep)[len(rep)//2]}")
    print(f"  builds that went GREEN after a repeat           {len(green_after)}   <- NOT waste")
    print()
    if not rows:
        print("  Nothing to report: no log had two reconstructable fix rounds. That is a statement")
        print("  about this reconstruction, not about the harness.")
        return 0
    print("  worst offenders (rounds after the first repeat):")
    for r in sorted(rep, key=lambda x: -x["after_repeat"])[:8]:
        g = "went green" if r["green"] else "never green"
        print(f"    {r['name']:44s} {r['rounds']}r {r['distinct']}d  repeat@{r['first_repeat']}  "
              f"+{r['after_repeat']} after  {g}")
    print()
    ksweep(rows)
    print()
    print("  ⚠️ NOT COMPARABLE to the 27 counted on 29 July: that used the error-LINE-SET signature,")
    print("  this uses the whole-output fingerprint with the 31 July timestamp normalisation.")
    print("  ⚠️ A round after a repeat is not automatically waste — see the green column.")
    return 0


def self_test() -> int:
    ok = True

    def chk(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: {got!r} != {want!r}")

    def log(*errs: str) -> str:
        out = []
        for e in errs:
            out.append("[guildlm-build] compile/test FAILED, fix round x")
            for ln in e.split("|"):
                out.append(f"[guildlm-build]     ! {ln}")
        return "\n".join(out)

    ident = lambda s: s

    chk("one round -> no verdict", analyse(log("a"), ident), None)
    r = analyse(log("a", "b", "c"), ident)
    chk("no repeat -> first_repeat None", r["first_repeat"], None)
    chk("no repeat -> after 0", r["after_repeat"], 0)

    r = analyse(log("a", "b", "b", "b"), ident)
    chk("repeat at 3", r["first_repeat"], 3)
    chk("one round after it", r["after_repeat"], 1)
    chk("distinct counted", r["distinct"], 2)
    chk("in budget", r["in_budget"], True)

    # the real arm shape: A B C C C C C C -> first repeat at 4, four rounds after
    r = analyse(log("a", "b", "c", "c", "c", "c", "c", "c"), ident)
    chk("arm shape repeat@4", r["first_repeat"], 4)
    chk("arm shape after=4", r["after_repeat"], 4)

    # a repeat that lands PAST the budget is not the policy's case
    r = analyse(log("a", "b", "c", "d", "e", "f", "a"), ident)
    chk("repeat at 7 is out of budget", r["in_budget"], False)

    # the reconstruction must not merge two rounds when the marker is missing
    chk("rounds counted from the marker", len(rounds_of(log("a", "b"))), 2)

    # ---- k_fire: CONSECUTIVE, which is the predicate the whole policy turns on ----
    S = lambda *xs: list(xs)
    chk("k=2 fires on the second of a pair", k_fire(S("a", "b", "b", "b"), 2), 3)
    chk("k=3 needs a third",                 k_fire(S("a", "b", "b", "b"), 3), 4)
    chk("k=4 never reached",                 k_fire(S("a", "b", "b", "b"), 4), None)
    # THE DISCRIMINATOR. Set-based `first_repeat` says 3; a run-based rule must say never.
    chk("alternating never fires",           k_fire(S("a", "b", "a", "b"), 2), None)
    chk("...though it DOES repeat",          analyse(log("a", "b", "a", "b"), ident)["first_repeat"], 3)
    # the real arm shape A B C C C C: run of 4 c's, k=3 fires on the 5th round of 6
    chk("arm shape k=3 fires at 5",          k_fire(S("a", "b", "c", "c", "c", "c"), 3), 5)
    chk("run must be unbroken",              k_fire(S("a", "a", "b", "a", "a"), 3), None)
    chk("empty is not a fire",               k_fire([], 2), None)
    try:
        k_fire(S("a", "a"), 1)
        chk("k=1 must be rejected", "no raise", "ValueError")
    except ValueError:
        pass

    # ksweep must count a green as killed even when it fires on the LAST round
    row = {"sigs": S("a", "b", "b"), "rounds": 3, "green": True}
    chk("fires on last round -> 0 saved", 3 - k_fire(row["sigs"], 2), 0)
    chk("...and still kills the green", bool(row["green"] and k_fire(row["sigs"], 2)), True)

    # ── a log file is not a build ──
    one = ("[guildlm-build] compile/test FAILED, fix round 1\n[guildlm-build]     ! boom\n"
           "[guildlm-build] converged to green after fix round 1\n"
           "Generated shortener into ./generated/x\n")
    two = one + one
    chk("two builds in one file are split", len(builds_of(two)), 2)
    chk("...and neither has 2 rounds", [analyse(b, ident) for b in builds_of(two)], [None, None])
    chk("merged, it would look like one build repeating", analyse(two, ident)["rounds"], 2)
    chk("a single-build log is not split", len(builds_of(one)), 1)
    # ⚠️ THE CASE THE FIRST SEGMENTER MISSED: no "(1/N)" line anywhere. iso-shortener-07170020
    # is exactly this shape and stayed merged, so the tool reported one build repeating 4 times.
    chk("split works with no (1/N) line", len(builds_of(two)), 2)
    # a FAILED build prints no "Generated ... into" — it must still terminate
    fail = ("[guildlm-build] compile/test FAILED, fix round 1\n[guildlm-build]     ! boom\n"
            "[guildlm-build] exhausted 6 fix rounds (5 budgeted), still failing\n")
    chk("a failed build terminates too", len(builds_of(fail + one)), 2)
    chk("an in-flight trailing build is kept",
        len(builds_of(one + "[guildlm-build] compile/test FAILED, fix round 1\n")), 2)

    # ── the green detector, and the two traps it fell into ──
    chk("real success line detected",
        bool(_GREEN.search("[guildlm-build] converged to green after fix round 1 (deterministic)")), True)
    chk("FIX 1's warning is NOT green",
        bool(_GREEN.search("[guildlm-build] WARNING: internal/store/memory.go came out EMPTY "
                           "(build never went green) - a sibling did its job")), False)
    chk("the trailing 'Generated x into y' line is not the marker",
        bool(_GREEN.search("Generated ledger into ./generated/x")), False)

    print("  self-test: OK — repeats located, in-budget separated, rounds-after counted"
          if ok else "  self-test: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(sweep(sorted((pathlib.Path(__file__).parent / "logs").glob("*.log"))))
