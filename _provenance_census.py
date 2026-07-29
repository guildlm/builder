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
and ab-bitset-v4-07261610.log is 07-26 16:11. The gap is PRINTED on every matched row, and
anything unmatched says WHY on its own line — RESTORED, no ab-log, or nearest-log-is-N-hours —
rather than being guessed at. The whole point is to stop attributing things to the wrong run.
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
    """When the draw stopped writing .go files, and whether every .go shares ONE second.

    TWO THINGS THE OBVIOUS VERSION GETS WRONG, both found by the tool reporting UNKNOWN for
    12 of 23 artifacts and the count being too high to accept.

    1. NEWEST FILE, NOT NEWEST .go. taskapipro-v4's source is a coherent 07-19 draw and its
       go.mod alone was rewritten 07-26 15:19 by a later corpus fix — as was ledger-v4's, to
       the same second. Keying on the newest FILE dated both trees a week after their draw
       and lost the campaign's namesake artifact and ledger. Keying on the newest .go file
       matches ab-taskapipro-v4-07191617.log and ab-ledger-v4-07171610.log exactly.

    2. A ZERO SPREAD MEANS THE TREE WAS COPIED, NOT DRAWN. A draw writes files one at a time,
       seconds apart — every genuinely-drawn tree in this corpus has a spread of 43-879s.
       Eleven v4 trees have EVERY .go file on the same second, and four different specs
       share the SAME second (07-27 02:01:08) — which no set of four independent generations
       produces. So one operation wrote them and their timestamp says when that happened, not
       when they were built. WHAT the operation was is NOT established: nothing in this repo
       copies into generated/<spec>-v4. The label is RESTORED because that is the shape;
       treat it as "single-second write, draw undatable", not as a known history.
    """
    gos = [f.stat().st_mtime for f in tree.rglob("*.go") if f.is_file()]
    if not gos:
        return None, False
    restored = len(gos) >= 3 and max(gos) == min(gos)
    return max(gos), restored


GENLINE = re.compile(r"^\[guildlm-build\] generate (\S+) \(\d+/(\d+)\)", re.M)


def match_by_fileset(artifact: str, gen: str, tree: pathlib.Path) -> tuple[pathlib.Path | None, str]:
    """Fallback when time fails: which candidate log GENERATED this exact set of files?

    A build log names every file it wrote. Specs are edited over a corpus's life, so the file
    set is a fingerprint of the SPEC VERSION — and where a spec gained or lost a file, that
    fingerprint separates draws that timestamps cannot.

    MEASURED REACH, so nobody expects more of it than it gives: run against the seven
    artifacts whose v4 trees carry a single-second mtime, it disambiguates exactly ONE.
    taskflow-v4 has 15 files and only one of its 19 candidate logs generated 15 — the rest
    produced 12, 13 or 14. For the other six the file set is identical across every draw, so
    this returns nothing at all. One in seven is worth having because taskflow carries 47 of
    the capstone's 140 live rows; it is not a general rescue.

    ⚠️ AND IT IS A CANDIDATE, NOT A PROOF, which is why the match method is printed on every
    row. taskflow-v4's bytes carry an mtime NINE HOURS after the log it matches closed, and
    what performed that write is unidentified. The file set says which spec version produced
    the tree; it cannot say which run wrote those bytes.
    """
    files = {str(p.relative_to(tree)) for p in tree.rglob("*") if p.is_file()}
    hits = []
    for cand in sorted(LOGS.glob(f"ab-{artifact}-{gen}-*.log")):
        gen_set = {m.group(1) for m in GENLINE.finditer(cand.read_text(errors="ignore"))}
        if gen_set and gen_set == files:
            hits.append(cand)
    if len(hits) == 1:
        return hits[0], "FILE-SET (candidate, not proof)"
    if len(hits) > 1:
        return None, f"file set matches {len(hits)} logs — identifies nothing"
    return None, "no log generated this file set"


def match_log(artifact: str, gen: str, tree: pathlib.Path) -> tuple[pathlib.Path | None, float, str]:
    """The build log whose close is nearest the tree's last .go write. Gap never hidden."""
    t, restored = tree_mtime(tree)
    if t is None:
        return None, float("inf"), "no .go files"
    if not restored:
        best, best_gap = None, float("inf")
        for cand in LOGS.glob(f"ab-{artifact}-{gen}-*.log"):
            gap = abs(cand.stat().st_mtime - t)
            if gap < best_gap:
                best, best_gap = cand, gap
        if best is not None and best_gap <= GAP_LIMIT:
            return best, best_gap, ""
    # Time failed — either the tree was written in one second, or no log is near it.
    fs, why = match_by_fileset(artifact, gen, tree)
    if fs is not None:
        return fs, float("nan"), why
    reason = "RESTORED — every .go file shares one mtime" if restored else "no log near in time"
    return None, float("inf"), f"{reason}; and {why}"


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
            a["match"] = why or "time"
            rows[art][gen] = a
            outcome = ("converged(det)" if a["deterministic_only"] else
                       "converged" if a["converged"] else
                       "EXHAUSTED" if a["exhausted"] else "?")
            gapstr = "  n/a" if gap != gap else f"{gap:>6.0f}"
            print(f"{art:<22} {gen:<4} {log.name:<30} {gapstr} {a['model']:>6} "
                  f"{a['model_tests']:>7} {a['deterministic']:>5} {a['drained']:>6} "
                  f"{a['rounds']:>5}  {outcome}")
            if a["match"] != "time":
                print(f"{'':27}matched by {a['match']}")
            if a["model_files"]:
                # PER-FILE, because artifact-level is the wrong grain for a ROW: what can move
                # a mutation verdict on middleware.go is a rewrite of middleware.go. Grading
                # the capstone's flips this way took them from 2-of-8 clean to 6-of-8.
                print(f"{'':27}model-rewrote: {', '.join(a['model_files'])}")

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
