#!/usr/bin/env python3
"""Do the times written INTO the evidence files match when they were actually committed?

    python _check_timestamps.py            # audit every tracked logs/*.txt
    python _check_timestamps.py --self-test

WHY. Eighteen fabricated timestamps in one day, in two batches of nine, both written the same
way: typing the time it felt like rather than reading one. The first batch was caught by
chance while checking something else; the second by noticing the clock said 16:56 while a file
claimed 17:24. Neither was caught by looking for it, and a header time that is an hour off is
invisible to every other check in this repo — the prose reads exactly as well.

    A file's COMMIT TIME is authoritative and free. It cannot be typed wrong, because nobody
    types it. Comparing the two turns a whole class of confident-and-wrong into a diff.

WHAT IT DOES NOT DO. It does not stop a header being written wrong; it finds it afterwards.
That is the right trade here — the alternative is a helper that must be remembered at exactly
the moment attention is elsewhere, which is the moment the error happens.

TOLERANCE. A file is written, then committed minutes later, sometimes after another edit. The
default window is 45 minutes and errors of interest are hours. An APPENDED correction block
carrying its own time is checked too — the file is committed at the append, so a correction
block's time should sit near the LATEST commit, not the first.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
TOLERANCE_MIN = 45

# A CLAIM about when this file was written, not a reference to when something else happened.
# `Written 16:35.` and `16:54 on 29 July.` at the start of a line; `CORRECTION (16:45) —` as a
# section heading.
STAMP = re.compile(r"^(?:Written\s+)?(\d{1,2}):(\d{2})(?=\D)")
HEADING_STAMP = re.compile(r"^[A-Z][^()\n]{0,60}\((\d{1,2}):(\d{2})\)")
RULE = re.compile(r"^[=-]{10,}$")


def claim_stamps(text: str) -> set[tuple[int, int]]:
    """Times this file claims for ITSELF, not times it mentions.

    THE FALSE POSITIVES THAT FORCED THIS, and they were all three of the tool's first hits:

        "...a defect recorded as UNEXPLAINED at 10:02 and confirmed as"   a cross-reference
        "12:10 at 612c4f3. My inference was one step from the page"      a commit reference
        "  sweep (00:51, process A): 82.9%  NOT-GREEN"                   run labels in a table

    Every one is a legitimate mention of another event's time. A check that flags those is a
    check that gets ignored, and an ignored check is worse than none — the repo already has a
    note about a green that belonged to another tool.

    TWO CONDITIONS, and both are needed. The stamp must sit at the START of a line (or be a
    parenthesised section heading), which drops the mid-sentence references. AND the line must
    be in a CLAIM REGION: the first eight lines, or within two lines either side of a ==== or
    ---- rule, which is where this repo puts headings. The docstring above claimed
    "header region only" while the code scanned the whole file — the comment was right and
    the code was not, which is the exact defect shape this repo keeps finding in itself.
    """
    lines = text.splitlines()
    rules = [i for i, ln in enumerate(lines) if RULE.match(ln.strip())]
    region = set(range(min(8, len(lines))))
    for i in rules:
        region.update(range(max(0, i - 2), min(len(lines), i + 4)))
    out = set()
    for i in sorted(region):
        # A HEADER CLAIM STARTS A PARAGRAPH. The last false positive was a line WRAP:
        #     "...it was born 07-16\n12:10 at 612c4f3. My inference was false."
        # which begins a line with a time only because the sentence broke there. Requiring a
        # blank line or a rule above it separates a heading from a continuation, and every
        # real claim in this repo — "Written 16:35.", "16:54 on 29 July.", an appended
        # "CORRECTION (16:45)" — opens a paragraph.
        if i and lines[i - 1].strip() and not RULE.match(lines[i - 1].strip()):
            continue
        for rx in (STAMP, HEADING_STAMP):
            m = rx.match(lines[i])
            if m:
                out.add((int(m.group(1)), int(m.group(2))))
    return out


def commit_times(rel: str) -> list[dt.datetime]:
    """Every commit that touched this path, oldest first, as local naive datetimes."""
    out = subprocess.run(
        ["git", "log", "--follow", "--pretty=%ad", "--date=format:%Y-%m-%d %H:%M", "--", rel],
        cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        return []
    times = [dt.datetime.strptime(ln.strip(), "%Y-%m-%d %H:%M")
             for ln in out.stdout.splitlines() if ln.strip()]
    return sorted(times)


def nearest_gap(stamp_min: int, commits: list[dt.datetime]) -> int:
    """Smallest |written - committed| in minutes, over every commit that touched the file.

    ANY commit, not the first: a file appended to at 16:48 and again at 16:55 legitimately
    carries three different times in three blocks. Requiring each to match the FIRST commit
    would flag every correction block in the repo, and a check that cries wolf on the repo's
    own convention gets ignored, which is worse than not having it.
    """
    best = 10 ** 9
    for c in commits:
        best = min(best, abs(c.hour * 60 + c.minute - stamp_min))
    return best


def audit(paths: list[pathlib.Path], tolerance: int = TOLERANCE_MIN) -> int:
    bad = 0
    checked = 0
    for p in paths:
        rel = str(p.relative_to(ROOT))
        commits = commit_times(rel)
        if not commits:
            continue
        text = p.read_text(errors="ignore")
        stamps = claim_stamps(text)
        if not stamps:
            continue
        checked += 1
        offenders = []
        for h, m in sorted(stamps):
            if h > 23 or m > 59:
                continue
            gap = nearest_gap(h * 60 + m, commits)
            if gap > tolerance:
                offenders.append((f"{h:02d}:{m:02d}", gap))
        if offenders:
            bad += 1
            print(f"\n⚠ {rel}")
            print(f"   committed: {', '.join(c.strftime('%m-%d %H:%M') for c in commits[-4:])}")
            for s, gap in offenders:
                print(f"   claims {s} — nearest commit is {gap} min away "
                      f"({gap // 60}h{gap % 60:02d})")
    print(f"\n   {checked} file(s) carried a time; {bad} disagree with their commits by more "
          f"than {tolerance} min.")
    if not bad:
        print("   Every written time sits near a commit that touched the file.")
    return 1 if bad else 0


def self_test() -> int:
    fails = []
    hdr = ("RESULT — a title\n"
           "=================\n"
           "\n"
           "Written 16:35. The day produced 33 files and a defect recorded at 10:02 was\n"
           "confirmed later.\n")
    got = claim_stamps(hdr)
    if got != {(16, 35)}:
        fails.append(f"header must claim 16:35 only, not the 10:02 it MENTIONS; got {got}")
    body = ("t\n===========\n\nWritten 09:00.\n" + "filler\n" * 40 +
            "12:10 at 612c4f3. My inference was false.\n")
    if (12, 10) in claim_stamps(body):
        fails.append("a line-start time deep in the body is a reference, not a claim")
    appended = ("t\n=========\n\nWritten 09:00.\n" + "filler\n" * 20 +
                "\nCORRECTION (16:45) — the loop DID edit the test\n"
                "================================================\n")
    if claim_stamps(appended) != {(9, 0), (16, 45)}:
        fails.append(f"an appended correction heading is a claim; got {claim_stamps(appended)}")
    table = ("t\n=======\n\nWritten 09:00.\n\nrows\n----------\n"
             "  sweep (00:51, process A): 82.9%  NOT-GREEN\n")
    if (0, 51) in claim_stamps(table):
        fails.append("a run label inside a table is not a claim about the file")
    wrapped = ("t\n=======\n\nWritten 09:00.\n\nThe rule did not exist; it was born 07-16\n"
               "12:10 at 612c4f3. My inference was false.\n"
               "=============================================\n")
    if (12, 10) in claim_stamps(wrapped):
        fails.append("a time that begins a line only because the sentence WRAPPED there is "
                     "not a claim — it must follow a blank line or a rule")
    # Nearest-commit, not first-commit: an appended block matches a LATER commit.
    commits = [dt.datetime(2026, 7, 29, 16, 37), dt.datetime(2026, 7, 29, 16, 55)]
    if nearest_gap(16 * 60 + 54, commits) != 1:
        fails.append("an appended block must be allowed to match a later commit")
    if nearest_gap(17 * 60 + 24, commits) != 29:
        fails.append(f"gap to the nearest commit is wrong: {nearest_gap(17*60+24, commits)}")
    # The real failure this was built for: 17:24 written, committed 16:55 -> 29 min. Under a
    # 45-min tolerance that is NOT flagged, and that is the honest limit of this check.
    if nearest_gap(17 * 60 + 24, commits) > TOLERANCE_MIN:
        fails.append("the tolerance must be stated honestly, not tuned to catch this one case")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — header claims separated from cross-references, run labels and\n"
                           "           line wraps; nearest-commit used"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    unknown = [a for a in sys.argv[1:] if a.startswith("-")]
    if unknown:
        raise SystemExit(f"REFUSING: unknown flag(s) {' '.join(unknown)}. Takes --self-test.")
    tracked = subprocess.run(["git", "ls-files", "logs/*.txt"], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
    raise SystemExit(audit([ROOT / t for t in tracked]))
