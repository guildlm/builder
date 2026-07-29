#!/usr/bin/env python3
"""Score the pre-registered trajectory prediction mechanically, from a build log.

    python _grade_trajectory_prediction.py logs/inert-taskapipro-07291641.log
    python _grade_trajectory_prediction.py --self-test

WRITTEN BEFORE THE DATA EXISTED — 17:52 on 29 July, with the inert draw inside round 2 and
zero round-3 markers in its log. That is the whole point. A prediction graded by the person
who made it, after seeing the outcome, has a way of finding that it was basically right; the
defence is to fix the decision procedure in code first, the same way _grade_import_defect.py
was written before the inert draw's round 1 was read.

THE PREDICTION (logs/PREDICTION-does-the-inert-draw-follow-v5-round-for-round.txt)
    P1  85%  round 3 exists and reports "too many arguments in call to h.svc.List" in projects.go
    P2  70%  its site is 71:55 AND the round-4 site is 50:2 — the +12-line arm's pair
    P3  65%  round 4 reports "declared and not used: status" in projects.go
    P4  80%  the draw ends NOT-GREEN having exhausted its rounds
    P5  75%  round 3's only fix target is projects.go, no widening

P2 IS A PAIR AND IS GRADED AS ONE OUTCOME. The prediction file says so explicitly, and it says
so because the six-line offset was found BEFORE round 3 existed:

    chain5 (PRE-edit, no lines)  77:55 and 56:2      <- tracks the pre-edit base text
    v5 x2  (+12 lines)           71:55 and 50:2      <- tracks the added lines

Grading them separately would let a split outcome be reported as "one of two right", which is
exactly the post-hoc freedom this file exists to remove.

⚠️ A MISSING ROUND IS NOT A MISS. If the draw converges before round 3 or 4, the corresponding
prediction is VOID, not wrong — four predictions went void today for precisely this reason and
the standing rule from that is to put the "nothing happens" branch in the prediction set.
VOID is reported as VOID and excluded from the score.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROUND_HDR = re.compile(r"compile/test FAILED, fix round (\d+)/")
ERRLINE = re.compile(r"^\[guildlm-build\]\s+!\s+(.*?)\s*$")
FIXLINE = re.compile(r"^\[guildlm-build\]\s+fixing (\S+?\.go)(?: \(widened in\))?\s*$")
TOO_MANY = re.compile(r"(\S+\.go):(\d+):(\d+): too many arguments in call to h\.svc\.List")
UNUSED = re.compile(r"(\S+\.go):(\d+):(\d+): declared and not used: status")


def by_round(text: str):
    """{round: {"errors": [...], "fixes": [...]}} — fixes belong to the round they follow."""
    out, rnd = {}, 0
    for ln in text.splitlines():
        m = ROUND_HDR.search(ln)
        if m:
            rnd = int(m.group(1))
            out.setdefault(rnd, {"errors": [], "fixes": []})
            continue
        if rnd == 0:
            continue
        e = ERRLINE.match(ln)
        if e:
            out[rnd]["errors"].append(e.group(1))
            continue
        f = FIXLINE.match(ln)
        if f:
            out[rnd]["fixes"].append(f.group(1))
    return out


def grade(text: str) -> list[tuple[str, str, str]]:
    """[(id, verdict, detail)] with verdict in HIT / MISS / VOID."""
    r = by_round(text)
    converged = "converged to green after fix round" in text
    exhausted = "exhausted" in text and "fix rounds" in text
    out = []

    # P1
    if 3 not in r:
        out.append(("P1", "VOID", "no round 3 — the draw did not get there"
                                  + (" (converged)" if converged else "")))
    else:
        hit = [e for e in r[3]["errors"] if TOO_MANY.search(e)]
        out.append(("P1", "HIT" if hit else "MISS",
                    hit[0][:100] if hit else f"round 3 errors: {r[3]['errors'][:2]}"))

    # P2 — the PAIR, one outcome
    s3 = next((TOO_MANY.search(e) for e in r.get(3, {}).get("errors", []) if TOO_MANY.search(e)),
              None)
    s4 = next((UNUSED.search(e) for e in r.get(4, {}).get("errors", []) if UNUSED.search(e)),
              None)
    if not s3 or not s4:
        out.append(("P2", "VOID", "the pair needs BOTH sites; "
                                  f"round3={'yes' if s3 else 'no'} round4={'yes' if s4 else 'no'}"))
    else:
        pair = (f"{s3.group(2)}:{s3.group(3)}", f"{s4.group(2)}:{s4.group(3)}")
        if pair == ("71:55", "50:2"):
            out.append(("P2", "HIT", "71:55 + 50:2 — tracks the ADDED LINES"))
        elif pair == ("77:55", "56:2"):
            out.append(("P2", "MISS", "77:55 + 56:2 — tracks the PRE-EDIT BASE TEXT. This is "
                                      "the informative miss: the lines govern what is written "
                                      "first but not where repair lands."))
        else:
            out.append(("P2", "MISS", f"{pair[0]} + {pair[1]} — neither arm's pair"))

    # P3
    if 4 not in r:
        out.append(("P3", "VOID", "no round 4"))
    else:
        hit = [e for e in r[4]["errors"] if UNUSED.search(e)]
        out.append(("P3", "HIT" if hit else "MISS",
                    hit[0][:100] if hit else f"round 4 errors: {r[4]['errors'][:2]}"))

    # P4
    if converged:
        out.append(("P4", "MISS", "converged to green"))
    elif exhausted:
        out.append(("P4", "HIT", "exhausted its rounds, still failing"))
    else:
        out.append(("P4", "VOID", "the draw has not finished"))

    # P5
    if 3 not in r:
        out.append(("P5", "VOID", "no round 3"))
    else:
        fx = r[3]["fixes"]
        ok = fx == ["internal/api/projects.go"]
        out.append(("P5", "HIT" if ok else "MISS", f"round-3 targets: {fx}"))
    return out


def self_test() -> int:
    fails = []
    v5 = ("[guildlm-build] compile/test FAILED, fix round 3/6\n"
          "[guildlm-build]     ! internal/api/projects.go:71:55: too many arguments in call to h.svc.List\n"
          "[guildlm-build]   fixing internal/api/projects.go\n"
          "[guildlm-build] compile/test FAILED, fix round 4/6\n"
          "[guildlm-build]     ! internal/api/projects.go:50:2: declared and not used: status\n"
          "[guildlm-build]   fixing internal/api/projects.go\n"
          "[guildlm-build] exhausted 7 fix rounds (6 budgeted), still failing\n")
    g = dict((i, v) for i, v, _ in grade(v5))
    if g != {"P1": "HIT", "P2": "HIT", "P3": "HIT", "P4": "HIT", "P5": "HIT"}:
        fails.append(f"the v5 trajectory must score all HIT, got {g}")

    c5 = v5.replace("71:55", "77:55").replace("50:2", "56:2")
    g = dict((i, v) for i, v, _ in grade(c5))
    if g["P2"] != "MISS":
        fails.append("chain5's pair must MISS P2 — it is the discriminator")
    if g["P1"] != "HIT" or g["P3"] != "HIT":
        fails.append("chain5's pair still HITS P1 and P3 — the defect is there, the site is "
                     "what differs, and that is the informative miss")

    # A SPLIT PAIR MUST MISS, not half-count. This is the post-hoc freedom being removed.
    split = v5.replace("50:2", "56:2")
    if dict((i, v) for i, v, _ in grade(split))["P2"] != "MISS":
        fails.append("a split pair (71:55 with 56:2) must MISS as one outcome")

    conv = ("[guildlm-build] compile/test FAILED, fix round 1/6\n"
            "[guildlm-build]     ! x\n"
            "[guildlm-build] converged to green after fix round 1 (deterministic)\n")
    g = dict((i, v) for i, v, _ in grade(conv))
    if g["P1"] != "VOID" or g["P2"] != "VOID" or g["P3"] != "VOID":
        fails.append(f"a draw that converges makes the round-3/4 predictions VOID, not MISS: {g}")
    if g["P4"] != "MISS":
        fails.append("P4 predicted NOT-GREEN, so converging IS a miss, not a void")

    unfinished = "[guildlm-build] compile/test FAILED, fix round 2/6\n[guildlm-build]     ! x\n"
    if dict((i, v) for i, v, _ in grade(unfinished))["P4"] != "VOID":
        fails.append("an unfinished draw cannot score P4")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — v5 scores all HIT, chain5's pair misses P2 while hitting P1/P3, "
                           "a split pair misses as one, and a converged draw voids rather than misses"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if [a for a in sys.argv[1:] if a.startswith("-")]:
        raise SystemExit("REFUSING: takes --self-test or a build log.")
    if not args:
        raise SystemExit(__doc__)
    text = pathlib.Path(args[0]).read_text(errors="ignore")
    rows = grade(text)
    print(f"{pathlib.Path(args[0]).name}\n")
    for i, v, detail in rows:
        mark = {"HIT": "✓", "MISS": "✗", "VOID": "—"}[v]
        print(f"  {mark} {i}  {v:<5} {detail}")
    scored = [v for _, v, _ in rows if v != "VOID"]
    print(f"\n  {scored.count('HIT')} hit · {scored.count('MISS')} miss · "
          f"{len(rows) - len(scored)} void (excluded)")
