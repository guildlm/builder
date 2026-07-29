#!/usr/bin/env python3
"""Compare two draws on the files NEITHER fix loop touched — the only as-drawn comparison
available to draws that predate .pre-fix.json.

    python _untouched_diff.py <treeA> <treeB> <logA> <logB>
    python _untouched_diff.py --self-test

WHY IT IS THE FILES NEITHER LOOP TOUCHED. A tree on disk is the post-repair tree. Comparing
two of them conflates what the DRAWS produced with how much REPAIR each absorbed, which is the
error behind every retraction on 29 July. Restricting to files that appear in no fix line of
either build log removes that entirely: those bytes are as-drawn on both sides.

WHAT IT ADDS OVER A DIFF — the distinction that carried the presence/content result. Two draws
can differ in a comment or in a statement, and those are not the same finding:

    PROSE   the files differ ONLY inside comments and string literals. Strip both and the
            remainder is byte-identical. The model wrote the same program and worded it
            differently.
    CODE    something outside comments and strings differs. A different program.

Measured with it, on one denominator of seven files:
    two draws of one spec        0 differ
    +12 lines of DIFFERENT prose 1 differ, PROSE   (a comment's word order)
    +12 lines PRESENT vs absent  4 differ, CODE    (an entire getenv helper, a statement body)

⚠️ IT CANNOT SEE THE REPAIRED FILES, which are usually the interesting ones. That is the whole
reason `<out>/.pre-fix.json` exists; for draws that carry one, read the snapshot instead. This
is the best available answer for the corpus drawn before 18:17 on 29 July, and no better.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

FIX = re.compile(r"^\[guildlm-build\]\s+(?:fixing|deterministic fix in|"
                 r"rebuilt a request that was served twice \(drained body\) in) (\S+?\.go)",
                 re.M)
LINE_COMMENT = re.compile(r"//[^\n]*")
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
# Go strings: interpreted "..." (with escapes) and raw `...`.
STRINGS = re.compile(r'"(?:[^"\\\n]|\\.)*"' + r"|`[^`]*`")


def code_only(src: str) -> str:
    """The source with comments and string literals blanked, and whitespace normalised.

    Whitespace is normalised because gofmt reflows around an edit — a changed string literal
    can shift indentation on neighbouring lines, and reporting that as a CODE difference would
    turn the sharpest distinction this tool makes back into noise.
    """
    s = BLOCK_COMMENT.sub(" ", src)
    s = LINE_COMMENT.sub(" ", s)
    s = STRINGS.sub('""', s)
    return re.sub(r"\s+", " ", s).strip()


def touched(log: pathlib.Path) -> set[str]:
    return set(FIX.findall(log.read_text(errors="ignore"))) if log.is_file() else set()


def compare(a: pathlib.Path, b: pathlib.Path, ta: set[str], tb: set[str]) -> dict:
    fa = {str(p.relative_to(a)) for p in a.rglob("*.go")}
    fb = {str(p.relative_to(b)) for p in b.rglob("*.go")}
    common = fa & fb
    never = sorted(f for f in common if f not in ta and f not in tb)
    rows = []
    for f in never:
        sa, sb = (a / f).read_text(errors="ignore"), (b / f).read_text(errors="ignore")
        if hashlib.sha256(sa.encode()).digest() == hashlib.sha256(sb.encode()).digest():
            rows.append((f, "IDENTICAL", 0, 0))
        else:
            kind = "PROSE" if code_only(sa) == code_only(sb) else "CODE"
            rows.append((f, kind, len(sa), len(sb)))
    return {"never": never, "rows": rows,
            "only_a": sorted(fa - fb), "only_b": sorted(fb - fa)}


def self_test() -> int:
    fails = []
    base = 'package x\n\n// a helper\nfunc F() int {\n\treturn 1\n}\n'
    if code_only(base) != code_only(base.replace("// a helper", "// something else")):
        fails.append("a changed COMMENT must not survive code_only")
    if code_only(base) != code_only(base.replace("return 1", 'return 1 // note')):
        fails.append("an added trailing comment must not survive")
    s1 = 'package x\nfunc F() { t.Fatalf("long message: %v", err) }\n'
    s2 = 'package x\nfunc F() { t.Fatalf("short: %v", err) }\n'
    if code_only(s1) != code_only(s2):
        fails.append("a changed STRING LITERAL must not survive — that is the inert-vs-v5 "
                     "difference and calling it CODE would erase the finding")
    if code_only(base) == code_only(base.replace("return 1", "return 2")):
        fails.append("a changed RETURN VALUE must survive; this is the direction that must "
                     "never be blurred")
    if code_only(base) == code_only(base.replace("func F() int {\n\treturn 1\n}\n", "")):
        fails.append("a deleted function must survive")
    # gofmt reflow around an edit must not read as CODE.
    if code_only('package x\nfunc F() {\n\tg("a")\n}\n') != code_only('package x\nfunc F() {\n    g("bb")\n}\n'):
        fails.append("indentation changes around a string edit must not read as CODE")
    # A string containing what looks like code must still be treated as a string.
    if code_only('package x\nvar s = "func G() {}"\n') != code_only('package x\nvar s = "func H() {}"\n'):
        fails.append("code-looking text INSIDE a string is still a string")
    if FIX.findall("[guildlm-build]   fixing a.go\n[guildlm-build]   deterministic fix in b.go\n") != ["a.go", "b.go"]:
        fails.append("both fix kinds mark a file as touched")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — comments and strings blanked, gofmt reflow ignored, changed "
                           "values and deletions survive"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(args) != 4:
        raise SystemExit(__doc__)
    A, B, LA, LB = (pathlib.Path(x) for x in args)
    for p in (A, B):
        if not p.is_dir():
            raise SystemExit(f"REFUSING: {p} is not a directory.")
    r = compare(A, B, touched(LA), touched(LB))
    n = len(r["never"])
    if n == 0:
        print("  NOTHING IS COMPARABLE: every common .go file was touched by a fix in one draw")
        print("  or the other, so no byte here is as-drawn on both sides. Not a null result.")
        raise SystemExit(2)
    counts = {}
    for f, kind, sa, sb in r["rows"]:
        counts[kind] = counts.get(kind, 0) + 1
        if kind != "IDENTICAL":
            print(f"  {kind:<10} {f:<40} {sa} vs {sb} bytes")
    print(f"\n  untouched in both: {n} · " + " · ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if r["only_a"] or r["only_b"]:
        print(f"  ⚠ files present in only one tree: A-only {r['only_a']} · B-only {r['only_b']}")
    if counts.get("CODE"):
        print("  CODE differences mean the two draws wrote different PROGRAMS, not different "
              "wording.")
    elif counts.get("PROSE"):
        print("  Only PROSE differs: same program, different comments or message strings.")
    raise SystemExit(0)
