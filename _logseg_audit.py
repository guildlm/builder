#!/usr/bin/env python3
"""Cross-check the build segmenter against the archive using invariants it must never violate.

    ./_logseg_audit.py            # audit every log
    ./_logseg_audit.py --self-test

WHY THIS EXISTS. Six instrument bugs were found on 31 July. Two were caught by self-test cases.
FOUR WERE CAUGHT BY LUCK:

    green detector matched "never went green"     a 0 that happened to be surprising
    a log file is not a build                     a contradiction I happened to read
    start-based segmenter missed 160 builds       two instruments happening to disagree
    a failing build's tail cut off                a build I happened to remember reading

Every one of those was noticed because a number looked odd to a person who had just read the
underlying log. That is not a method — it does not scale past the logs I happen to remember, and
it fails silently the moment a wrong number looks plausible.

These invariants are the mechanical version. Each is a property the segmentation must have for
ANY log, checkable without knowing the right answer, and each maps to a bug that actually happened.

⚠️ A CHECKER THAT HAS NEVER FIRED IS NOT A CHECKER. The self-test plants each violation and
requires it to be detected, so the audit's silence means something.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _logseg import BUILD_FAIL, BUILD_OK, build_count, builds_of  # noqa: E402

# ⚠️ ANY generate line, not just (1/N). def-cov.log holds a build whose captured output is
# TRUNCATED — its visible builder lines run from (3/17) to (13/17) and it never reaches a fix
# round, so a (1/N)-only pattern called it an orphan tail. It is a real build, just an
# incomplete one. Widening here does not weaken the check: a genuine detached tail is repair
# and warning lines, which contain no generate lines at all.
_ACTIVITY = re.compile(r"generate \S+ \(\d+/\d+\)|=== plan|compile/test (FAILED|passed)")
_BUILDER = re.compile(r"^\[guildlm-build\]", re.M)
_CONVERGED = re.compile(r"converged to green")


def violations(text: str) -> list[str]:
    """Every invariant this text breaks. Empty means the segmentation is self-consistent."""
    out: list[str] = []
    segs = builds_of(text)

    # 1. PARTITION — segmentation must lose nothing and duplicate nothing. The cheapest and
    #    strongest structural check there is.
    if "".join(segs) != text:
        out.append("PARTITION: segments do not reconstruct the original text")

    # 2. ORPHAN TAIL — this is the 31 July bug. A segment with builder output but NO outcome
    #    and NO build activity is a build's tail that got detached from its build.
    #
    #    ⚠️ ONLY FOR LOGS THAT CONTAIN A BUILD. Running this over the archive flagged 10 files,
    #    every one of them build_count=0: TOOL logs. _repair_survival.py and the sweep drivers
    #    call builder functions, so they emit "[guildlm-build] ..." lines while containing no
    #    build at all. A tail cannot be orphaned from a build that does not exist. Skipping them
    #    costs nothing, because a segmenter that lost EVERY outcome is caught by COUNT below —
    #    build_count reads the whole text and would disagree with the segments.
    for i, s in enumerate(segs if build_count(text) else [], 1):
        has_outcome = bool(BUILD_OK.search(s) or BUILD_FAIL.search(s))
        if has_outcome or not _BUILDER.search(s):
            continue
        if not _ACTIVITY.search(s):
            out.append(f"ORPHAN TAIL: segment {i} has builder output, no outcome, no build start")

    # 3. OUTCOME AGREEMENT — two ways of counting builds must agree. This is the check that
    #    exposed 654-vs-853, made mechanical.
    seg_outcomes = sum(bool(BUILD_OK.search(s) or BUILD_FAIL.search(s)) for s in segs)
    if seg_outcomes != build_count(text):
        out.append(f"COUNT: {seg_outcomes} segments carry an outcome, build_count says {build_count(text)}")

    # 4. EXCLUSIVITY — one build cannot both converge and exhaust. Two builds merged into one
    #    segment is exactly how that becomes possible.
    for i, s in enumerate(segs, 1):
        if _CONVERGED.search(s) and BUILD_FAIL.search(s):
            out.append(f"EXCLUSIVITY: segment {i} both converged and exhausted")
        if len(BUILD_OK.findall(s)) > 1:
            out.append(f"EXCLUSIVITY: segment {i} carries {len(BUILD_OK.findall(s))} success markers")

    return out


def audit(paths: list[pathlib.Path]) -> int:
    bad = 0
    kinds: dict[str, int] = {}
    for p in paths:
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        if not text.strip():
            continue
        v = violations(text)
        if v:
            bad += 1
            if bad <= 12:
                print(f"  {p.name}")
                for x in v[:3]:
                    print(f"      {x}")
        for x in v:
            kinds[x.split(":")[0]] = kinds.get(x.split(":")[0], 0) + 1

    print(f"\n  logs audited     {len(paths)}")
    print(f"  logs violating   {bad}")
    if kinds:
        print("  by kind:", ", ".join(f"{k}={n}" for k, n in sorted(kinds.items())))
    else:
        print("\n  No violation anywhere. That is a claim about these four invariants only —")
        print("  a segmentation can be wrong in ways none of them can see, and today's tail bug")
        print("  passed PARTITION and COUNT while being wrong. ORPHAN TAIL is the one that")
        print("  would have caught it, and it was added AFTER the bug, not before.")
    return 1 if bad else 0


def self_test() -> int:
    ok = True

    def chk(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: {got!r} != {want!r}")

    green = ("[guildlm-build] compile/test FAILED, fix round 1\n"
             "[guildlm-build] converged to green after fix round 1\n"
             "Generated shortener into ./generated/x\n")
    red = ("[guildlm-build] compile/test FAILED, fix round 1\n"
           "[guildlm-build] exhausted 6 fix rounds (5 budgeted), still failing\n")
    tail = ("[guildlm-build]   left internal/store/memory.go empty: moving MemStore into it breaks\n"
            "[guildlm-build]   WARNING: internal/store/memory.go came out EMPTY (build never went green)\n")

    chk("a clean green log is silent", violations(green), [])
    chk("a clean failing log is silent", violations(red), [])
    chk("a failing log WITH a tail is silent", violations(red + tail), [])
    chk("several builds are silent", violations(green + red + tail + green), [])
    # a TOOL log: builder-prefixed lines, no build. Must not be reported as an orphan tail.
    tool = ("[guildlm-build]   moved MemStore from internal/store/store.go into memory.go\n"
            "[guildlm-build]   left internal/store/memory.go empty: moving it does nothing\n")
    chk("a tool log with no build is silent", violations(tool), [])
    # a TRUNCATED build: real activity, no outcome, and its visible output does not start at (1/N)
    trunc = green + ("[guildlm-build] generate internal/api/tasks.go (13/17)\n"
                     "[guildlm-build]     best-of-N gen: kept candidate 1 of 2\n")
    chk("a truncated build is not an orphan tail", violations(trunc), [])
    # NOTE: there is no "green + tail fires" case here, and that was my first instinct. With the
    # FIXED segmenter the tail attaches, so nothing fires and nothing should — the assertion I
    # wrote assumed the buggy segmenter while calling the fixed one. Detection is tested properly
    # below, by substituting the actual broken implementation.

    # ── each invariant must FIRE on the bug it was written for ──
    import _logseg

    real = _logseg.builds_of

    def orphaning(text):
        """the 31 July bug: split after the terminator, never re-attach the tail"""
        segs, cur = [], []
        for line in text.splitlines(keepends=True):
            cur.append(line)
            if _logseg.BUILD_END.search(line):
                segs.append("".join(cur))
                cur = []
        if cur and "".join(cur).strip():
            segs.append("".join(cur))
        return segs or [text]

    _logseg.builds_of = orphaning
    globals()["builds_of"] = orphaning
    v = violations(red + tail)
    chk("ORPHAN TAIL fires on the real bug", any(x.startswith("ORPHAN TAIL") for x in v), True)

    def losing(text):
        return [s for s in orphaning(text) if "WARNING" not in s]

    _logseg.builds_of = losing
    globals()["builds_of"] = losing
    chk("PARTITION fires when a line is dropped",
        any(x.startswith("PARTITION") for x in violations(red + tail)), True)

    def merging(text):
        return [text]

    _logseg.builds_of = merging
    globals()["builds_of"] = merging
    v = violations(green + red)
    chk("COUNT fires when builds are merged", any(x.startswith("COUNT") for x in v), True)
    chk("EXCLUSIVITY fires on converge+exhaust", any(x.startswith("EXCLUSIVITY") for x in v), True)
    chk("EXCLUSIVITY fires on two successes",
        any("success markers" in x for x in violations(green + green)), True)

    _logseg.builds_of = real
    globals()["builds_of"] = real
    chk("restored", violations(green + red + green), [])

    print("  self-test: OK — all four invariants fire on the bug they were written for"
          if ok else "  self-test: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(audit(sorted((pathlib.Path(__file__).parent / "logs").glob("*.log"))))
