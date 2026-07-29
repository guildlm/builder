#!/usr/bin/env python3
"""How much REPAIR did each tree absorb before its mutation rows were measured?

    python _provenance_census.py                 # every artifact with both generations
    python _provenance_census.py taskflow bitset # named artifacts only
    python _provenance_census.py --self-test

WHY THIS EXISTS, and it is the root cause of both retractions on 29 July. A mutation sweep
reads a tree ON DISK and grades CAUGHT/SURVIVED. A tree on disk is the POST-REPAIR tree. For
the question "does this artifact defend that invariant?" that is exactly right — the shipped
tree is the deliverable, and how it got there does not matter.

    But the CAPSTONE asks a different question: "did this closure survive a REDRAW?" That is
    a claim about what a SPEC produces. If the v4 tree converged after one deterministic fix
    and the v5 tree absorbed seven model rewrites, a verdict that differs between them may be
    the LOOP's work rather than the draw's, and the row is not evidence about the closure.

Both retractions came from comparing exactly such a mismatched pair without knowing it —
chain4 (one deterministic fix, converged) against v5 (three model rewrites of both test files,
never compiled). Nothing in either tool's output distinguished them. This makes the difference
visible for every artifact in the corpus at once.

WHAT COUNTS AS SPOILING PROVENANCE
    `fixing <file>`                        a MODEL rewrite. Rewrites whatever it likes:
                                           assertions, seeding, names. SPOILS.
    `deterministic fix in <file>`          goimports-class. Does not touch assertions or
                                           seeding. Does NOT spoil.
    `rebuilt a request ... (drained body)`  replaces a request; assertions untouched. Reported
                                           separately because it CHANGES HOW MANY ITEMS LAND,
                                           which is a setup quantity even though no assertion
                                           moved.

MATCHING A LOG TO A TREE, and a wrong match is a silent wrong answer
There are 407 ab-*.log files and up to four per (artifact, generation) across different dates.
The build log is written throughout the run and closed at the end, so its mtime lands within
seconds of the tree's newest file. Verified: generated/bitset-v4's newest file is 07-26 16:11
and ab-bitset-v4-07261610.log is 07-26 16:11. The gap is PRINTED on every row and a gap over
the threshold is reported UNKNOWN rather than guessed — the whole point is to stop attributing
things to the wrong run.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
LOGS, GEN = ROOT / "logs", ROOT / "generated"
GAP_LIMIT = 300  # seconds between tree's newest file and the log's close

FIXING = re.compile(r"^\[guildlm-build\]\s+fixing (\S+?\.go)(?: \(widened in\))?\s*$", re.M)
DETERMINISTIC = re.compile(r"^\[guildlm-build\]\s+deterministic fix in (\S+?\.go)\s*$", re.M)
DRAINED = re.compile(r"^\[guildlm-build\]\s+rebuilt a request that was served twice "
                     r"\(drained body\) in (\S+?\.go)\s*$", re.M)
ROUND = re.compile(r"^\[guildlm-build\] compile/test FAILED, fix round (\d+)/(\d+)", re.M)
CONVERGED = re.compile(r"^\[guildlm-build\] converged to green after fix round (\d+)"
                       r"( \(deterministic\))?", re.M)
EXHAUSTED = re.compile(r"^\[guildlm-build\] exhausted (\d+) fix rounds", re.M)


def tree_mtime(tree: pathlib.Path) -> tuple[float | None, bool]:
    """When the draw stopped writing .go files, and whether the tree was RESTORED wholesale.

    TWO THINGS THE OBVIOUS VERSION GETS WRONG, both found by the tool reporting UNKNOWN for
    12 of 23 artifacts and the count being too high to accept.

    1. NEWEST FILE, NOT NEWEST .go. taskapipro-v4's source is a coherent 07-19 draw and its
       go.mod alone was rewritten 07-26 15:19 by a later corpus fix — as was ledger-v4's, to
       the same second. Keying on the newest FILE dated both trees a week after their draw
       and lost the campaign's namesake artifact and ledger. Keying on the newest .go file
       matches ab-taskapipro-v4-07191617.log and ab-ledger-v4-07171610.log exactly.

    2. A ZERO SPREAD MEANS THE TREE WAS COPIED, NOT DRAWN. A draw writes files one at a time,
       seconds apart — every genuinely-drawn tree in this corpus has a spread of 43-879s.
       Eleven v4 trees have EVERY .go file on the same second, which is a wholesale restore
       and makes their timestamp say when they were copied, not when they were built. Their
       provenance is unrecoverable by time and the tool must say RESTORED rather than pick
       whichever log happens to sit nearest a copy operation.
    """
    gos = [f.stat().st_mtime for f in tree.rglob("*.go") if f.is_file()]
    if not gos:
        return None, False
    restored = len(gos) >= 3 and max(gos) == min(gos)
    return max(gos), restored


def match_log(artifact: str, gen: str, tree: pathlib.Path) -> tuple[pathlib.Path | None, float, str]:
    """The build log whose close is nearest the tree's last .go write. Gap never hidden."""
    t, restored = tree_mtime(tree)
    if t is None:
        return None, float("inf"), "no .go files"
    if restored:
        return None, float("inf"), "RESTORED — every .go file shares one mtime"
    best, best_gap = None, float("inf")
    for cand in LOGS.glob(f"ab-{artifact}-{gen}-*.log"):
        gap = abs(cand.stat().st_mtime - t)
        if gap < best_gap:
            best, best_gap = cand, gap
    if best is None:
        return None, float("inf"), "no ab-log for this artifact and generation"
    if best_gap > GAP_LIMIT:
        return None, best_gap, f"nearest log is {best_gap / 3600:.1f}h away"
    return best, best_gap, ""


def analyse(text: str) -> dict:
    """Repair absorbed, split by what it can and cannot change."""
    model = FIXING.findall(text)
    det = DETERMINISTIC.findall(text)
    drained = DRAINED.findall(text)
    rounds = [int(a) for a, _ in ROUND.findall(text)]
    conv = CONVERGED.search(text)
    return {
        "model": len(model),
        "model_tests": sum(1 for p in model if p.endswith("_test.go")),
        "model_files": sorted(set(model)),
        "deterministic": len(det),
        "drained": len(drained),
        "rounds": max(rounds) if rounds else 0,
        "converged": bool(conv),
        "deterministic_only": bool(conv and conv.group(2)),
        "exhausted": bool(EXHAUSTED.search(text)),
    }


def clean(a: dict) -> bool:
    """A tree whose numbers can be read as the DRAW's: no model rewrite touched it."""
    return a["model"] == 0


def self_test() -> int:
    fails = []
    log = (
        "[guildlm-build] compile/test FAILED, fix round 1/6\n"
        "[guildlm-build]   deterministic fix in internal/api/router_test.go\n"
        "[guildlm-build]   rebuilt a request that was served twice (drained body) in internal/api/x_test.go\n"
        "[guildlm-build]   fixing internal/api/projects_test.go\n"
        "[guildlm-build] compile/test FAILED, fix round 2/6\n"
        "[guildlm-build]   fixing internal/api/projects.go (widened in)\n"
        "[guildlm-build] exhausted 7 fix rounds (6 budgeted), still failing\n"
    )
    a = analyse(log)
    if a["model"] != 2:
        fails.append(f"two `fixing` lines must count 2 model rewrites, got {a['model']}")
    if a["model_tests"] != 1:
        fails.append("only the _test.go rewrite counts toward model_tests")
    if a["deterministic"] != 1 or a["drained"] != 1:
        fails.append("deterministic and drained-body must be counted separately from model")
    if a["rounds"] != 2 or not a["exhausted"] or a["converged"]:
        fails.append(f"round/outcome parse wrong: {a['rounds']} exhausted={a['exhausted']}")
    if clean(a):
        fails.append("a tree with model rewrites is NOT clean")

    det_only = ("[guildlm-build] compile/test FAILED, fix round 1/6\n"
                "[guildlm-build]   deterministic fix in internal/api/projects_test.go\n"
                "[guildlm-build] converged to green after fix round 1 (deterministic)\n")
    b = analyse(det_only)
    if not clean(b):
        fails.append("deterministic-only convergence is CLEAN — chain4 is the only clean tree "
                     "in the whole four-draw comparison and this is what says so")
    if not b["deterministic_only"] or not b["converged"]:
        fails.append("`converged ... (deterministic)` must be recognised")
    # A model fix with no rounds at all must still spoil.
    if clean(analyse("[guildlm-build]   fixing a.go\n")):
        fails.append("a model rewrite spoils provenance even with no round header")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — model/deterministic/drained separated, rounds and outcome "
                           "parsed, and deterministic-only counts as clean"))
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    want = [a for a in argv if not a.startswith("-")]
    pairs = []
    for tree in sorted(GEN.glob("*-v4")):
        art = tree.name[:-3]
        if want and art not in want:
            continue
        if (GEN / f"{art}-v5").is_dir():
            pairs.append(art)
    if not pairs:
        print("no artifact has both a -v4 and a -v5 tree")
        return 2

    print(f"{'artifact':<22} {'gen':<4} {'log':<30} {'gap':>6} {'model':>6} "
          f"{'(test)':>7} {'det':>5} {'drain':>6} {'rnds':>5}  outcome")
    print("-" * 118)
    rows = {}
    for art in pairs:
        rows[art] = {}
        for gen in ("v4", "v5"):
            tree = GEN / f"{art}-{gen}"
            log, gap, why = match_log(art, gen, tree)
            if log is None:
                print(f"{art:<22} {gen:<4} {('UNMATCHED — ' + why)[:44]:<44}")
                rows[art][gen] = None
                continue
            a = analyse(log.read_text(errors="ignore"))
            rows[art][gen] = a
            outcome = ("converged(det)" if a["deterministic_only"] else
                       "converged" if a["converged"] else
                       "EXHAUSTED" if a["exhausted"] else "?")
            print(f"{art:<22} {gen:<4} {log.name:<30} {gap:>6.0f} {a['model']:>6} "
                  f"{a['model_tests']:>7} {a['deterministic']:>5} {a['drained']:>6} "
                  f"{a['rounds']:>5}  {outcome}")

    print("\nPROVENANCE VERDICT PER ARTIFACT — can a v4-vs-v5 row difference be read as the DRAW's?")
    both_clean = mismatched = both_dirty = unknown = 0
    for art in pairs:
        a, b = rows[art]["v4"], rows[art]["v5"]
        # ONE SIDE IS OFTEN ENOUGH. If the v5 tree absorbed model rewrites, a v4-vs-v5
        # difference is already unattributable to the draw and the v4 log cannot rescue it.
        # Reporting that as "UNKNOWN" throws away a verdict the evidence supports.
        if b is not None and not clean(b) and a is None:
            print(f"   {art:<22} ⚠ UNATTRIBUTABLE — v5 absorbed {b['model']} model rewrite(s); "
                  f"v4 unmatched but cannot rescue it")
            mismatched += 1
        elif a is None or b is None:
            known = "v5 CLEAN, v4 unverified" if b is not None and clean(b) else "neither side known"
            print(f"   {art:<22} PARTIAL — {known}")
            unknown += 1
        elif clean(a) and clean(b):
            print(f"   {art:<22} CLEAN BOTH — no model rewrite either side. Row differences "
                  f"are the draw's.")
            both_clean += 1
        elif clean(a) != clean(b):
            dirty = "v5" if clean(a) else "v4"
            n = (b if dirty == "v5" else a)["model"]
            print(f"   {art:<22} ⚠ MISMATCHED — {dirty} absorbed {n} model rewrite(s), the "
                  f"other none. THIS IS THE RETRACTED SHAPE.")
            mismatched += 1
        else:
            print(f"   {art:<22} both repaired — v4 {a['model']}, v5 {b['model']} model "
                  f"rewrite(s). Comparable only if you argue the amounts are close.")
            both_dirty += 1
    print(f"\n   {both_clean} clean-both · {mismatched} MISMATCHED · {both_dirty} both-repaired "
          f"· {unknown} unknown   (of {len(pairs)} artifacts)")
    print("\n   MISMATCHED is the shape that produced both of 29 July's retractions: a tree that\n"
          "   converged on deterministic fixes compared against one the model rewrote. It does\n"
          "   NOT invalidate a sweep's verdict ABOUT AN ARTIFACT — the shipped tree is the\n"
          "   deliverable. It invalidates reading a v4-vs-v5 difference as a fact about the SPEC.")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    unknown = [a for a in sys.argv[1:] if a.startswith("-")]
    if unknown:
        raise SystemExit(f"REFUSING: unknown flag(s) {' '.join(unknown)}. "
                         f"Takes --self-test or a list of artifact names.")
    raise SystemExit(main(sys.argv[1:]))
