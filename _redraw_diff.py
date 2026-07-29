#!/usr/bin/env python3
"""Compare two corpus sweeps: what does a full REGENERATION change about the verdicts?

The durability programme has been asking "does this closure survive the next run?" one spec
at a time, and had answered it for two of five. Rebuilding the whole corpus answers it for
every spec at once: the same specs, the same model, a week apart, every artifact redrawn.
The rows file is git-tracked precisely so that comparison exists — this reduces it to a
table instead of a 170-line diff nobody reads.

    python _redraw_diff.py logs/hole-hunt-rows.tsv logs/hole-hunt-rows-new.tsv
    python _redraw_diff.py --self-test

WHAT IT REFUSES TO DO
  A row is (artifact, file, shape, verdict), and the same shape recurs at SEVERAL SITES in
  one file — so rows are keyed by their ordinal too, or 45% of the tracked corpus collapses
  into 82 keys before anything is compared. Only rows present in both sweeps are
  comparable; everything else is a site that moved, appeared or vanished —
  which is a finding of its own and not a verdict change. Both denominators are printed,
  because "3 flips" out of 12 comparable rows and out of 150 rows are different sentences,
  and the corpus headline has already been wrong once for exactly this reason
  (FINDING-status-code-holes: 64 of 150 probes could answer, not 150).

  The GENERATION SUFFIX is stripped before keying, so `taskapipro-v4` and `taskapipro-v5`
  are the same artifact. Without that this tool answered its own reason for existing with
  "NOTHING WAS COMPARED" — see _GEN_SUFFIX below. The generations actually present in each
  file are printed on the first line, so a v4-vs-v4 re-sweep can never be read as a redraw.
"""
from __future__ import annotations

import collections
import pathlib
import re
import sys

# NOTESTS: a tree with no _test.go survives every mutation, which is not a verdict
# about defence — see _teeth_suite.verdict_for.
# MUTANT-BROKEN joins the dead verdicts: a mutation the compiler rejects is not a
# measurement of anything, so it can neither gain nor lose a defence across a redraw.
# No row carries it yet — it was added to _teeth_suite on 29 July — so this is a no-op
# for every comparison already published and correct for the next sweep.
DEAD = ("BASELINE-RED", "NOAPPLY", "SKIP", "NOTESTS", "MUTANT-BROKEN")

# THE GENERATION SUFFIX IS METADATA, NOT IDENTITY — and this was wrong until 29 July.
#
# _hole_hunt writes `art.name`, the DIRECTORY name, so a row says `taskapipro-v4` in the
# baseline and `taskapipro-v5` after a redraw. Keyed raw, those two never match, and this
# tool answers a cross-generation comparison with 0 COMPARABLE and "NOTHING WAS COMPARED".
#
# Proven on the tracked baseline: 314 rows diffed against a copy of ITSELF with only the
# suffix rewritten reported 314 gone, 314 fresh, nothing compared. Byte-identical verdicts,
# zero of them comparable.
#
# It went unseen because every previous use was v4-vs-v4. _rebuild_corpus.sh and
# _resweep_v4.sh both regenerate `generated/<spec>-v4` IN PLACE, so both sides of every
# diff ever run carried the same suffix. --gen= was added to _hole_hunt precisely so a
# redraw could be swept without overwriting the baseline, and this half of the pair was
# never taught about it. The tool was correct for every comparison it had done and wrong
# for the only one it was built for.
#
# The self-test did not catch it because the self-test plants `a-v4` on BOTH sides — it was
# calibrated to the tool as built, which is the failure recorded three times already this
# week: a completeness check that shares its subject's blind spot. The cross-generation
# case is planted below now.
#
# NARROW ON PURPOSE: only a trailing -v<digits> is stripped. The corpus also holds -chain4,
# -witness and -empty trees, and those are DIFFERENT EXPERIMENTS on the same spec, not the
# same artifact at another generation. Collapsing them would silently compare a closure's
# purpose-built draw against a corpus draw and report the difference as durability.
_GEN_SUFFIX = re.compile(r"-v\d+$")


def base_artifact(art: str) -> str:
    """`taskapipro-v5` -> `taskapipro`; `tasks-api-v4` -> `tasks-api`; `x-chain4` unchanged."""
    return _GEN_SUFFIX.sub("", art)


def generations(path: pathlib.Path) -> list[str]:
    """Which generation suffixes a rows file actually contains, for the header line."""
    gens = set()
    for line in path.read_text().splitlines():
        if line.strip():
            art = line.split("\t")[0]
            m = _GEN_SUFFIX.search(art)
            gens.add(m.group(0)[1:] if m else "(none)")
    return sorted(gens)


def load(path: pathlib.Path) -> dict[tuple[str, str, str, int], str]:
    """Rows keyed by (artifact, file, shape, ORDINAL).

    The ordinal is not decoration. One file routinely carries the SAME shape at several
    sites — tasks-api-v4's handlers.go has eight `StatusBadRequest->StatusNotFound` rows,
    one per site — and a dict keyed by the first three fields keeps only the last of them.
    Measured on the tracked file: 149 rows collapse to 82 keys, so 45% of the corpus would
    have been dropped before anything was compared, and eight sites that can disagree would
    have been reported as one verdict.

    Sites are matched positionally within a group, which assumes the sweep visits them in
    the same order (it walks the file top-down, so it does). If a regeneration adds or
    removes a site, the surplus shows up as "only in one sweep" — which is the honest
    answer, not a verdict.
    """
    rows: dict[tuple[str, str, str, int], str] = {}
    seen: dict[tuple[str, str, str], int] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 4:
            raise SystemExit(f"{path}: expected 4 tab-separated fields, got {len(parts)}:\n  {line}")
        art, f, shape, verdict = parts
        # Generation stripped HERE, at the key, so every downstream set operation compares
        # artifacts rather than directory names. See _GEN_SUFFIX above.
        art = base_artifact(art)
        n = seen.get((art, f, shape), 0)
        seen[(art, f, shape)] = n + 1
        rows[(art, f, shape, n)] = verdict
    return rows


def compare(old: dict, new: dict) -> dict:
    both = sorted(set(old) & set(new))
    flips = [(k, old[k], new[k]) for k in both if old[k] != new[k]]
    # A flip between two DEAD verdicts (NOAPPLY -> BASELINE-RED) says nothing about
    # defence; separate it so it cannot pad the headline.
    live = [f for f in flips if not (f[1] in DEAD and f[2] in DEAD)]
    return {
        "comparable": both,
        "flips": flips,
        "live_flips": live,
        "gone": sorted(set(old) - set(new)),
        "fresh": sorted(set(new) - set(old)),
        "transitions": collections.Counter((o, n) for _, o, n in flips),
    }


def render(res: dict, old: dict, new: dict) -> str:
    out = []
    out.append(f"rows: {len(old)} old · {len(new)} new · {len(res['comparable'])} COMPARABLE "
               f"(same artifact+file+shape in both)")
    out.append(f"      {len(res['gone'])} site(s) only in the old sweep, "
               f"{len(res['fresh'])} only in the new — moved, added or lost, NOT verdict changes")
    # LIVE IN BOTH is the real denominator, and it is not `comparable`.
    #
    # A row is comparable when the same site exists in both sweeps. It is ANSWERABLE only
    # when neither side is DEAD — a BASELINE-RED row records that the artifact would not
    # compile, so no mutation on it could have been caught by anything. CAUGHT -> SURVIVED,
    # the one transition that can retract a claim, is observable ONLY on rows live in both.
    #
    # For the v4-vs-v5 capstone this is not a rounding detail. Four artifacts ship red —
    # taskapi, expreval, taskapipro, workapi — carrying 146 of the 314 baseline rows, 46%.
    # Reporting "N flips of 314 comparable" would describe a corpus half of which was never
    # measured. Printing this line first is the whole point; the number after it is only
    # meaningful against it.
    both_live = [k for k in res["comparable"] if old[k] not in DEAD and new[k] not in DEAD]
    out.append(f"      {len(both_live)} row(s) LIVE IN BOTH — the only rows where a verdict "
               f"change is observable at all")
    out.append(f"flips: {len(res['flips'])} of {len(res['comparable'])} comparable "
               f"({len(res['live_flips'])} involving a live verdict, "
               f"{len(both_live)} answerable)")
    if res["transitions"]:
        out.append("")
        for (o, n), c in sorted(res["transitions"].items(), key=lambda kv: -kv[1]):
            tag = "  (both dead — says nothing about defence)" if o in DEAD and n in DEAD else ""
            out.append(f"   {c:>3}  {o:<13} -> {n}{tag}")
    # A DEAD -> LIVE flip is not a defence change. Every one of the twenty rebuilt specs came
    # back GREEN on the base model, where the pre-deletion corpus was a mix of green and red
    # archives — so rows that read BASELINE-RED or NOTESTS before will read CAUGHT or
    # SURVIVED now simply because there is finally a suite to ask. Counted on its own line so
    # it cannot be read as the corpus getting better at defending itself.
    measurable = [(k, o, n) for k, o, n in res["live_flips"] if o in DEAD and n not in DEAD]
    silenced = [(k, o, n) for k, o, n in res["live_flips"] if n in DEAD and o not in DEAD]
    if measurable or silenced:
        out.append(f"\n   {len(measurable)} row(s) became MEASURABLE (dead verdict -> live) and "
                   f"{len(silenced)} went dead.\n   Those are artifacts changing state, not "
                   f"defences changing.")
    # A FLIP WHOSE GROUP CHANGED SIZE IS NOT A VERDICT CHANGE.
    #
    # Rows are matched by ORDINAL within (artifact, file, shape). If a redraw inserts a site
    # EARLIER in the file, every later ordinal shifts by one and this tool compares two
    # DIFFERENT sites while reporting a flip. The docstring above anticipates added and
    # removed sites and expects the surplus to surface as "only in one sweep" — which is
    # true only when the surplus is at the END.
    #
    # Measured on the 29 July capstone: taskflow's pagination.go held ONE `boundary <= -> <`
    # site in v4 and TWO in v5, the new one earlier in the file. Ordinal 0 compared
    # ParsePage's new line against Paginate's old one and reported DEFENCE LOST. Paginate's
    # site was CAUGHT in both draws. Nine of 170 live flips sat in groups whose size changed,
    # and removing them took the headline from "12 gained, 3 lost" to "6 gained, 2 lost".
    #
    # This is a REPORTING addition — it changes no key and no verdict — which is why it is
    # safe to add between a pair of sweeps when widening a mutation shape is not.
    def _sizes(d):
        c: collections.Counter = collections.Counter()
        for k in d:
            c[(k[0], k[1], k[2])] += 1
        return c
    so, sn = _sizes(old), _sizes(new)
    shifted = [(k, o, n) for k, o, n in res["live_flips"]
               if so[(k[0], k[1], k[2])] != sn[(k[0], k[1], k[2])]]
    if shifted:
        out.append(f"\n   ⚠️ {len(shifted)} of {len(res['live_flips'])} live flip(s) sit in a "
                   f"group whose SITE COUNT CHANGED between sweeps.")
        out.append("      Ordinals cannot align there — these compare different sites and are "
                   "NOT verdict changes:")
        for (a, f, sh, i), o, n in shifted:
            out.append(f"      {o:<13} -> {n:<13} {a:<14} {f:<20} {sh[:30]:<30} "
                       f"v4={so[(a, f, sh)]} v5={sn[(a, f, sh)]}")

    # RELOCATED SITES: same artifact and shape, but the file it lives in CHANGED entirely.
    #
    # The site-count warning above catches a group that gained or lost sites. It cannot catch
    # a group that MOVED, because the key includes the file: a mutation site that migrates from
    # internal/store/memory.go to internal/store/store.go simply vanishes from one side and
    # appears on the other. Not a flip, not a site-count change — silently absent from
    # `comparable`, with nothing printed.
    #
    # MEASURED, 29 July: it happens, and systematically. ledger, taskapipro and workapi each
    # moved their `reverse sort by ID` site from memory.go to store.go between v4 and v5 —
    # three artifacts, one direction. It cost this capstone NOTHING only because all three
    # v5-side rows landed BASELINE-RED and were unanswerable anyway. The same relocation with
    # a green tree would have dropped live rows without a word.
    #
    # The mechanism is real and independently observed: _iso-workapi-without-3 relocated its
    # whole store implementation between those two files, leaving memory.go as `package store`
    # alone. One draw in three, in that condition.
    _fileset_old, _fileset_new = {}, {}
    for k in old:
        _fileset_old.setdefault((base_artifact(k[0]), k[2]), set()).add(k[1])
    for k in new:
        _fileset_new.setdefault((base_artifact(k[0]), k[2]), set()).add(k[1])
    relocated = []
    for key in sorted(set(_fileset_old) & set(_fileset_new)):
        o_files, n_files = _fileset_old[key], _fileset_new[key]
        if o_files != n_files and not (o_files & n_files):
            relocated.append((key, sorted(o_files), sorted(n_files)))
    if relocated:
        out.append(f"\n   ⚠️ {len(relocated)} (artifact, shape) group(s) RELOCATED to a "
                   f"different file between sweeps.")
        out.append("      These are absent from `comparable` entirely — not flips, not "
                   "site-count changes, just")
        out.append("      dropped. Any verdict change in them is INVISIBLE to this diff:")
        for (a, sh), o_f, n_f in relocated:
            out.append(f"      {a:<14} {sh[:34]:<34} {', '.join(o_f)} -> {', '.join(n_f)}")

    lost = [(k, o, n) for k, o, n in res["live_flips"] if o == "CAUGHT" and n == "SURVIVED"]
    won = [(k, o, n) for k, o, n in res["live_flips"] if o == "SURVIVED" and n == "CAUGHT"]
    if lost:
        out.append("\n   DEFENCE LOST in the redraw (was CAUGHT, now SURVIVED):")
        for (a, f, s, i), _, _ in lost:
            out.append(f"      {a:<28} {f:<18} {s}" + (f"  [site {i+1}]" if i else ""))
    if won:
        out.append("\n   DEFENCE GAINED in the redraw (was SURVIVED, now CAUGHT):")
        for (a, f, s, i), _, _ in won:
            out.append(f"      {a:<28} {f:<18} {s}" + (f"  [site {i+1}]" if i else ""))
    if not res["comparable"]:
        out.append("\n   NOTHING WAS COMPARED. Every site moved or changed shape, so this "
                   "says nothing\n   about durability — it says the two sweeps do not "
                   "describe the same corpus.")
    return "\n".join(out)


def self_test() -> int:
    """Plant every transition this is supposed to separate, and require it to separate them."""
    old = {("a-v4", "h.go", "drop X", 0): "CAUGHT",       # -> SURVIVED  (defence lost)
           ("b-v4", "h.go", "drop X", 0): "SURVIVED",     # -> CAUGHT    (defence gained)
           ("c-v4", "h.go", "drop X", 0): "CAUGHT",       # unchanged
           ("d-v4", "h.go", "drop X", 0): "NOAPPLY",      # -> BASELINE-RED (both dead)
           ("e-v4", "h.go", "drop X", 0): "CAUGHT"}       # site vanishes
    new = {("a-v4", "h.go", "drop X", 0): "SURVIVED",
           ("b-v4", "h.go", "drop X", 0): "CAUGHT",
           ("c-v4", "h.go", "drop X", 0): "CAUGHT",
           ("d-v4", "h.go", "drop X", 0): "BASELINE-RED",
           ("f-v4", "h.go", "drop X", 0): "CAUGHT"}       # a site that is new
    res = compare(old, new)
    fail = []
    if len(res["comparable"]) != 4:
        fail.append(f"comparable should be 4 (e/f are not shared), got {len(res['comparable'])}")
    if len(res["flips"]) != 3:
        fail.append(f"3 verdicts changed, got {len(res['flips'])}")
    if len(res["live_flips"]) != 2:
        fail.append(f"the NOAPPLY->BASELINE-RED flip must not count as live, got "
                    f"{len(res['live_flips'])} live")
    if [k for k, o, n in res["live_flips"] if o == "CAUGHT" and n == "SURVIVED"] != \
            [("a-v4", "h.go", "drop X", 0)]:
        fail.append("the CAUGHT->SURVIVED row is not reported as defence lost")
    if len(res["gone"]) != 1 or len(res["fresh"]) != 1:
        fail.append("a vanished site and a new site must be counted separately from flips")
    # THE COLLAPSE. Three sites of one shape in one file must survive loading as three
    # rows; keyed by the first three fields they became one, and the tracked file loses 67
    # of its 149 rows that way.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as fh:
        fh.write("a-v4\th.go\tdrop X\tCAUGHT\n" * 2 + "a-v4\th.go\tdrop X\tSURVIVED\n")
        tmp = fh.name
    loaded = load(pathlib.Path(tmp))
    if len(loaded) != 3:
        fail.append(f"three sites of one shape must load as three rows, got {len(loaded)}")
    # Key is ("a", ...) not ("a-v4", ...): load() strips the generation suffix now, and this
    # assertion is the one place the self-test can SEE that it does. It failed the moment
    # normalization went in, which is the check doing its job on its own author.
    if loaded.get(("a", "h.go", "drop X", 2)) != "SURVIVED":
        fail.append("the third site's verdict is not preserved under its own ordinal")
    pathlib.Path(tmp).unlink()
    # THE CROSS-GENERATION CASE — the one this file was built for and could not do.
    #
    # Every assertion above plants `a-v4` on BOTH sides, so all of them passed while the
    # tool reported 0 COMPARABLE for a v4-vs-v5 diff of identical verdicts. A self-test
    # that only exercises same-generation rows is calibrated to the bug. This plants the
    # real shape: same artifact, same file, same shape, DIFFERENT generation suffix, one
    # verdict changed — and requires the comparison to happen and the flip to be seen.
    def _tsv(text: str) -> pathlib.Path:
        with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as fh:
            fh.write(text)
            return pathlib.Path(fh.name)

    v4 = _tsv("taskapipro-v4\tprojects.go\tclamp\tSURVIVED\n"
              "tasks-api-v4\th.go\tdrop X\tCAUGHT\n")
    v5 = _tsv("taskapipro-v5\tprojects.go\tclamp\tCAUGHT\n"
              "tasks-api-v5\th.go\tdrop X\tCAUGHT\n")
    xg = compare(load(v4), load(v5))
    if len(xg["comparable"]) != 2:
        fail.append(f"a v4-vs-v5 diff of the same two sites must compare BOTH, got "
                    f"{len(xg['comparable'])} — the generation suffix is being keyed as identity")
    if len(xg["gone"]) or len(xg["fresh"]):
        fail.append("a pure generation change must not read as sites appearing and vanishing")
    if [k for k, o, n in xg["live_flips"] if o == "SURVIVED" and n == "CAUGHT"] != \
            [("taskapipro", "projects.go", "clamp", 0)]:
        fail.append("the cross-generation SURVIVED->CAUGHT flip is not reported as defence gained")
    # ...and the hyphenated name must keep its hyphens: tasks-api-v4 -> tasks-api, not tasks.
    if ("tasks-api", "h.go", "drop X", 0) not in xg["comparable"]:
        fail.append("a hyphenated artifact lost more than its generation suffix")
    # ...while a DIFFERENT EXPERIMENT on the same spec must stay distinct from a generation.
    if base_artifact("taskapipro-chain4") != "taskapipro-chain4":
        fail.append("-chain4 is another experiment, not another generation; it must not collapse")
    v4.unlink(); v5.unlink()
    # And the denominator rule: two sweeps sharing NOTHING must say so rather than print 0 flips.
    empty = compare({("x-v4", "h.go", "s", 0): "CAUGHT"}, {("y-v4", "h.go", "s", 0): "CAUGHT"})
    if "NOTHING WAS COMPARED" not in render(empty, {}, {}):
        fail.append("two sweeps with no shared row must refuse, not report '0 flips'")
    for f in fail:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fail else "ok — every planted transition separated"))
    return 1 if fail else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    o, n = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    for p in (o, n):
        if not p.is_file():
            raise SystemExit(f"{p} is not a file")
    # Say WHICH generations are being compared, on the first line, before any number.
    # This session's recurring failure is a sentence whose answer is right and whose SUBJECT
    # is not what it looks like; the generation suffix was silently deciding the subject of
    # this entire comparison. Printing it makes a v4-vs-v4 diff impossible to mistake for a
    # v4-vs-v5 one, which is exactly how "0 regressions" could be read off the wrong pair.
    go_, gn_ = generations(o), generations(n)
    print(f"comparing {o.name} [{', '.join(go_)}]  ->  {n.name} [{', '.join(gn_)}]")
    if go_ == gn_:
        print(f"   note: BOTH sides are generation {', '.join(go_)} — this is a re-sweep of the "
              f"same trees,\n         not a redraw comparison.")
    print()
    old, new = load(o), load(n)
    print(render(compare(old, new), old, new))
