#!/usr/bin/env python3
"""Compare two draws AS DRAWN, from the .pre-fix.json snapshots, on every file.

    python _asdrawn_diff.py <treeA> <treeB> [--target=<relpath>]
    python _asdrawn_diff.py --self-test

WHY THIS EXISTS SEPARATELY FROM _untouched_diff.py. That tool answers the same question for
draws with no snapshot, and it pays a heavy price to do it: it can only compare files that NO
fix loop touched in EITHER draw, which are usually the least interesting ones. Once both sides
carry `<out>/.pre-fix.json` the restriction is unnecessary — every file is as-drawn — and the
denominator goes from "the ones nobody repaired" to "all of them".

WHY IT IS BEING WRITTEN NOW, WHICH IS LATE. The nine-arm spec-edit series was graded as-drawn
on the full file set — "CODE 7 · IDENTICAL 7 · PROSE 1" is fifteen of fifteen files, not the
seven _untouched_diff.py could have reached. That grading was done with an ad-hoc snippet
retyped per arm, and the collateral count, which is the column the whole series turns on, was
read off by eye. Two other instruments this week shipped with a completeness check calibrated
to their own bug. An eyeballed number in a headline is the same class of mistake with no
instrument at all, so the ad-hoc snippet is being replaced by something with a self-test.

IT REFUSES RATHER THAN FALLING BACK. If either tree lacks a snapshot this exits 2 and says
which one. It does NOT quietly compare the trees on disk instead: those are POST-REPAIR, and
mistaking a post-repair tree for a draw is the single error behind every retraction on 29 July.
A tool that silently degrades to the wrong measurement is worse than one that stops.

THE TARGET/COLLATERAL SPLIT. `--target=` names the file the spec edit was supposed to change.
Everything else that differs is COLLATERAL. Two counts the series needed and computed by hand:
    did the edit LAND      the target file differs (or, if it does not, that is a null edit
                           and the arm measures nothing — reported as such, not as a null
                           RESULT, because they are different claims)
    COLLATERAL             how many files that the edit does not mention wrote different code

GRANULARITY WARNING, AND IT IS THE REASON FOR THE --rename FLAG AND THE FUNCTION PASS. The
first arm graded with this tool came back "CODE 1, the target only, COLLATERAL 0" — and that
was WRONG in the only sense that matters. A word-order swap of a test NAME on ratelimit left
every other FILE identical and left the renamed test's own body identical, then rewrote a
DIFFERENT test in the same file, adding nine lines of assertions. File-level granularity
reported that as a clean null. So this tool now compares FUNCTIONS inside every differing file,
and the summary states collateral at both granularities. A "CODE 1, target only" row from a
file-level instrument is not a null; it is UNRESOLVED until someone looks inside the file.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

from _untouched_diff import code_only  # ONE copy of the classifier: two would drift, and the
                                       # PROSE/CODE distinction is the load-bearing part.

FUNC = re.compile(r"^func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(", re.M)


def _masked(src: str) -> str:
    """src with comments and string literals replaced by same-length blanks.

    Brace matching must not count a `{` that lives inside a string or a comment. Replacing with
    EQUAL-LENGTH blanks keeps every offset valid, so spans found on the mask slice the original.
    """
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        two = src[i:i + 2]
        if two == "//":
            j = src.find("\n", i)
            j = n if j < 0 else j
        elif two == "/*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif src[i] in '"`':
            q, j = src[i], i + 1
            while j < n and src[j] != q:
                j += 2 if (q == '"' and src[j] == "\\") else 1
            j = min(j + 1, n)
        else:
            i += 1
            continue
        for k in range(i, j):
            if out[k] != "\n":
                out[k] = " "
        i = j
    return "".join(out)


def spans(src: str) -> list[tuple[str, int, int]]:
    """[(name, start, end)] for each top-level func, by brace matching on the masked source.

    The span starts at the `func` KEYWORD, not at the opening brace, so the SIGNATURE is part of
    what gets compared. That is not a detail: renaming a receiver type — `StoreImpl` to `store`,
    which one arm did to nine methods — changes every signature and no body. Comparing bodies
    alone reported that file as "0 of 9 functions differ" while it had lost 421 characters.
    """
    mask = _masked(src)
    out: list[tuple[str, int, int]] = []
    for m in FUNC.finditer(mask):
        open_brace = mask.find("{", m.end())
        if open_brace < 0:
            continue
        depth, i = 1, open_brace + 1
        while i < len(mask) and depth:
            depth += (mask[i] == "{") - (mask[i] == "}")
            i += 1
        out.append((m.group(1), m.start(), i))
    return out


def functions(src: str) -> dict[str, str]:
    """{name: signature-plus-body} for each top-level func."""
    return {n: src[s:e] for n, s, e in spans(src)}


def neutralise(text: str, renames: dict[str, str]) -> str:
    """code_only(text) with every declared rename collapsed to one placeholder on both sides.

    ONE copy, used by both the function pass and the RENAME-ONLY verdict. Two copies of this
    would drift, and it decides whether an arm counts as a null.

    Longest name first, so a rename target that is a PREFIX of another (TestGet / TestGetAll)
    cannot be half-substituted into a spurious difference.
    """
    for i, (old, new) in enumerate(sorted(renames.items(), key=lambda kv: -len(kv[0]))):
        text = text.replace(old, f"__R{i}__").replace(new, f"__R{i}__")
    return code_only(text)


def residue(src: str) -> str:
    """Everything OUTSIDE every top-level func: package clause, imports, type and var decls.

    Reported separately because a file can differ substantially with every function identical —
    a changed interface, an added import, a type renamed. Folding that into "none" is the same
    mistake as folding function-level collateral into a file-level null.
    """
    keep, last = [], 0
    for _, s, e in spans(src):
        keep.append(src[last:s])
        last = e
    keep.append(src[last:])
    return "".join(keep)


def load(tree: pathlib.Path) -> dict[str, str] | None:
    snap = tree / ".pre-fix.json"
    if not snap.is_file():
        return None
    return json.loads(snap.read_text(encoding="utf-8"))


def classify(a: dict[str, str], b: dict[str, str]) -> dict:
    """{'rows': [(file, kind)], 'only_a': [...], 'only_b': [...]} over the union of files."""
    common = sorted(set(a) & set(b))
    rows = []
    for f in common:
        if a[f] == b[f]:
            rows.append((f, "IDENTICAL"))
        else:
            rows.append((f, "PROSE" if code_only(a[f]) == code_only(b[f]) else "CODE"))
    return {"rows": rows,
            "only_a": sorted(set(a) - set(b)),
            "only_b": sorted(set(b) - set(a))}


def self_test() -> int:
    fails = []
    A = {"x.go": "package x\nfunc F() int { return 1 }\n",
         "y.go": "package x\n// a\nfunc G() {}\n",
         "z.go": "package x\nfunc H() {}\n"}
    B = {"x.go": "package x\nfunc F() int { return 2 }\n",   # CODE
         "y.go": "package x\n// b\nfunc G() {}\n",           # PROSE
         "z.go": "package x\nfunc H() {}\n"}                 # IDENTICAL
    r = classify(A, B)
    if dict(r["rows"]) != {"x.go": "CODE", "y.go": "PROSE", "z.go": "IDENTICAL"}:
        fails.append(f"the three-way classification is wrong: {r['rows']}")
    if r["only_a"] or r["only_b"]:
        fails.append("identical file sets must report no one-sided files")

    # A file present in only one draw is a bigger finding than any content difference, and it
    # must never be silently dropped from the union the way an inner-join comparison would.
    r2 = classify({"x.go": "package x\n"}, {"x.go": "package x\n", "extra.go": "package x\n"})
    if r2["only_b"] != ["extra.go"]:
        fails.append("a file present in only ONE draw must be reported, not dropped")
    if dict(r2["rows"]) != {"x.go": "IDENTICAL"}:
        fails.append("one-sided files must not corrupt the common-file rows")

    # The collateral count must EXCLUDE the target and must not be confused with "differs".
    r3 = classify({"t.go": "package x\nfunc F() { return }\n", "o.go": "package x\nvar A = 1\n"},
                  {"t.go": "package x\nfunc G() { return }\n", "o.go": "package x\nvar A = 2\n"})
    diff = [f for f, k in r3["rows"] if k == "CODE"]
    if collateral(diff, "t.go") != ["o.go"]:
        fails.append("collateral must exclude the target file")
    if collateral(diff, None) != ["o.go", "t.go"]:
        fails.append("with no target declared, every CODE file is collateral-unknown and must "
                     "still be listed")
    if collateral(diff, "absent.go") != ["o.go", "t.go"]:
        fails.append("a target that differs in NO file must not silently remove a real file "
                     "from the collateral list")

    # --- the function pass, added after a file-level null turned out to hide real collateral ---
    if functions("package x\nfunc A() { }\nfunc (r *T) B(i int) string { return \"}\" }\n") \
            .keys() != {"A", "B"}:
        fails.append("top-level funcs, including methods with receivers, must be found")
    # A brace inside a string literal must not end the body early. This is the case that makes
    # naive brace counting silently truncate a function and report it as changed.
    fs = functions('package x\nfunc A() {\n\ts := "{"\n\tg()\n}\nfunc B() {\n\th()\n}\n')
    if "g()" not in fs.get("A", "") or "h()" not in fs.get("B", ""):
        fails.append("a brace inside a STRING must not terminate the body — naive counting "
                     f"truncates here: {fs}")
    fs2 = functions('package x\nfunc A() {\n\t// }\n\tg()\n}\n')
    if "g()" not in fs2.get("A", ""):
        fails.append("a brace inside a COMMENT must not terminate the body")
    # The finding that forced this pass: same file, renamed func identical, OTHER func changed.
    src_a = 'package x\nfunc TestOld(t *T) {\n\tf()\n}\nfunc TestOther(t *T) {\n\tg()\n}\n'
    src_b = 'package x\nfunc TestNew(t *T) {\n\tf()\n}\nfunc TestOther(t *T) {\n\tg()\n\th()\n}\n'
    fd = func_diff(src_a, src_b, {"TestOld": "TestNew"})
    if fd["changed"] != ["TestOther"]:
        fails.append(f"the CHANGED function must be found across a rename: {fd}")
    if fd["renamed_body_changed"]:
        fails.append("the renamed function's body is identical here and must not be reported "
                     "as changed — that distinction is the whole finding")
    if fd["only_a"] or fd["only_b"]:
        fails.append("a declared rename must PAIR the two functions, not report both as "
                     "one-sided")
    # A RECEIVER TYPE rename changes every signature and no body. Comparing bodies alone
    # reported one real arm's store.go as "0 of 9 functions differ" while it lost 421 chars.
    rec_a = 'package x\nfunc (s *StoreImpl) Get() int {\n\treturn 1\n}\n'
    rec_b = 'package x\nfunc (s *store) Get() int {\n\treturn 1\n}\n'
    if func_diff(rec_a, rec_b, {})["changed"] != ["Get"]:
        fails.append("a changed RECEIVER TYPE must count as a changed function — the signature "
                     "is part of the span, not just the body")
    # A change entirely OUTSIDE every function must be reported, never folded into "none".
    out_a = 'package x\n\ntype S interface {\n\tA() int\n}\n\nfunc F() {\n\tg()\n}\n'
    out_b = 'package x\n\ntype S interface {\n\tA() int\n\tB() int\n}\n\nfunc F() {\n\tg()\n}\n'
    fdo = func_diff(out_a, out_b, {})
    if fdo["changed"]:
        fails.append("the function is identical here and must not be reported as changed")
    if not fdo["residue_differs"]:
        fails.append("a changed INTERFACE outside every func must be reported — folding it into "
                     "'none' repeats the false-null bug at a different granularity")
    if fdo["residue_delta"] <= 0:
        fails.append(f"residue delta must show growth here, got {fdo['residue_delta']}")
    # And a comment-only change outside functions must NOT trip the residue flag.
    if func_diff(out_a, out_a.replace("package x", "package x\n// note"), {})["residue_differs"]:
        fails.append("a COMMENT outside every func must not read as a residue change")

    # A PURE rename — name changes, body does not — must read as UNCHANGED once declared.
    pure_a = 'package x\nfunc TestOld(t *T) {\n\tf()\n}\n'
    pure_b = 'package x\nfunc TestNew(t *T) {\n\tf()\n}\n'
    fdp = func_diff(pure_a, pure_b, {"TestOld": "TestNew"})
    if fdp["changed"] or fdp["renamed_body_changed"]:
        fails.append(f"a PURE rename must not read as a changed function: {fdp}")
    # ...but a rename WITH a body change must still be caught.
    fdq = func_diff(pure_a, 'package x\nfunc TestNew(t *T) {\n\tf()\n\th()\n}\n',
                    {"TestOld": "TestNew"})
    if not fdq["renamed_body_changed"]:
        fails.append("a rename that ALSO changes the body must report renamed_body_changed")

    # The shared neutraliser: one copy, used by the function pass AND the RENAME-ONLY verdict.
    R = {"TestGet": "TestFetch"}
    if neutralise("func TestGet() {}", R) != neutralise("func TestFetch() {}", R):
        fails.append("a declared rename must neutralise to the same text on both sides")
    # The prefix trap this helper's ordering exists to avoid: TestGet is a prefix of TestGetAll,
    # so substituting the short name first would corrupt the long one into a false difference.
    R2 = {"TestGet": "TestFetch", "TestGetAll": "TestFetchAll"}
    if neutralise("func TestGetAll() {}", R2) != neutralise("func TestFetchAll() {}", R2):
        fails.append("a rename target that is a PREFIX of another must not be half-substituted")
    if neutralise("func TestGet() {}", R) == neutralise("func TestOther() {}", R):
        fails.append("an UNRELATED name must still differ after neutralising")

    # Without the rename map the same pair must show as one-sided rather than silently matched.
    fd2 = func_diff(src_a, src_b, {})
    if fd2["only_a"] != ["TestOld"] or fd2["only_b"] != ["TestNew"]:
        fails.append("with no rename declared, an unpaired func must be reported one-sided")

    # PROSE-only difference in the target: the edit did NOT land as code. That is a distinct
    # verdict from "the edit landed and nothing else moved", and conflating them would let a
    # null EDIT be reported as a null RESULT.
    r4 = classify({"t.go": "package x\n// one\nfunc F() {}\n"},
                  {"t.go": "package x\n// two\nfunc F() {}\n"})
    if dict(r4["rows"]) != {"t.go": "PROSE"}:
        fails.append("a comment-only change in the target must classify PROSE, so the report "
                     "can say the edit did not land in code")

    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — three-way classification, one-sided files reported, collateral "
                           "excludes the target, null edits stay distinguishable, and the "
                           "FUNCTION pass survives braces in strings/comments, pairs across a "
                           "declared rename and refuses to guess an undeclared one"))
    return 1 if fails else 0


def collateral(differing: list[str], target: str | None) -> list[str]:
    return sorted(f for f in differing if f != target)


def func_diff(a: str, b: str, renames: dict[str, str]) -> dict:
    """Which FUNCTIONS differ in code between two versions of one file.

    `renames` maps a name in A to its name in B. Undeclared renames deliberately surface as
    one-sided entries rather than being guessed at: a wrong pairing would invent a "changed
    body" out of two unrelated functions.
    """
    fa, fb = functions(a), functions(b)

    # The span includes the SIGNATURE, so without neutralising a pure rename would always read
    # as "changed" and the distinction the finding rests on — the name moved, the body did not —
    # would be unreportable.
    def neutral(text: str) -> str:
        return neutralise(text, renames)

    changed, only_a = [], []
    for name, body in fa.items():
        other = renames.get(name, name)
        if other in fb:
            if neutral(body) != neutral(fb[other]):
                changed.append(name)
        else:
            only_a.append(name)
    paired = {renames.get(n, n) for n in fa}
    ra, rb = residue(a), residue(b)
    return {"changed": sorted(changed), "only_a": sorted(only_a),
            "only_b": sorted(n for n in fb if n not in paired),
            "renamed_body_changed": any(
                n in changed for n in renames if n in fa and renames[n] in fb),
            "residue_differs": neutral(ra) != neutral(rb),
            "residue_delta": len(rb) - len(ra),
            "n_a": len(fa), "n_b": len(fb)}


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("-")]
    target = next((a.split("=", 1)[1] for a in argv if a.startswith("--target=")), None)
    if len(args) != 2:
        raise SystemExit(__doc__)
    A, B = (pathlib.Path(x) for x in args)
    snaps = {}
    for p in (A, B):
        if not p.is_dir():
            print(f"REFUSING: {p} is not a directory.")
            return 2
        s = load(p)
        if s is None:
            print(f"REFUSING: {p} carries no .pre-fix.json, so its as-drawn contents are not "
                  f"recoverable.")
            print("  NOT falling back to the tree on disk: that is POST-REPAIR, and reading a "
                  "repaired tree as a draw")
            print("  is the error behind every retraction on 29 July. For a snapshotless pair "
                  "use _untouched_diff.py,")
            print("  which answers a narrower question honestly.")
            return 2
        snaps[p] = s
    r = classify(snaps[A], snaps[B])
    counts: dict[str, int] = {}
    for f, kind in r["rows"]:
        counts[kind] = counts.get(kind, 0) + 1
    width = max((len(f) for f, _ in r["rows"]), default=10)
    for f, kind in r["rows"]:
        if kind == "IDENTICAL":
            continue
        la, lb = len(snaps[A][f]), len(snaps[B][f])
        mark = "  <- the TARGET" if f == target else ""
        print(f"  {kind:<10} {f:<{width}} {la} vs {lb} chars{mark}")
    total = len(r["rows"])
    # The denominator is stated in BOTH units on purpose. The ad-hoc grading this replaces
    # counted .go files only, so it reported 15 where this reports 16 for the same taskflow
    # pair — the extra file is go.mod, always IDENTICAL, which is why no CODE/PROSE/collateral
    # count ever moved. Printing one number would silently make old and new rows incomparable.
    ngo = sum(1 for f, _ in r["rows"] if f.endswith(".go"))
    print(f"\n  as-drawn on BOTH sides: {total} common file(s) ({ngo} .go + "
          f"{total - ngo} non-Go) · " + " · ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if r["only_a"] or r["only_b"]:
        print(f"  ⚠ present in only ONE draw — a bigger difference than any content change:")
        print(f"      {A.name}-only: {r['only_a'] or 'none'}")
        print(f"      {B.name}-only: {r['only_b'] or 'none'}")
    diff_code = [f for f, k in r["rows"] if k == "CODE"]
    if target is not None:
        kind = dict(r["rows"]).get(target)
        if kind is None:
            print(f"  ⚠ the declared target {target!r} is not a common file — check the name; "
                  f"the collateral count below cannot be trusted.")
        elif kind == "CODE":
            print(f"  edit landed in CODE: YES ({target})")
        else:
            print(f"  ⚠ edit did NOT land in code: {target} is {kind}. This arm measures a NULL "
                  f"EDIT, not a null RESULT — different claims.")
        col = collateral(diff_code, target)
        print(f"  COLLATERAL: {len(col)} of {len(diff_code)} CODE difference(s)"
              + (f" — {col}" if col else " — none"))
    elif diff_code:
        print(f"  {len(diff_code)} file(s) differ in CODE; no --target declared, so none of "
              f"them is attributed.")
    # THE FUNCTION PASS. A file-level "target only" verdict is not a null, and the first arm
    # graded here proved it: the renamed test's body was identical and a different test in the
    # same file gained nine assertion lines.
    renames = dict(r_.split(":", 1) for r_ in
                   [a.split("=", 1)[1] for a in argv if a.startswith("--rename=")])
    fn_collateral: list[str] = []
    changed_files = [f for f, k in r["rows"] if k in ("CODE", "PROSE")]
    if changed_files:
        print("\n  INSIDE each differing file, which FUNCTIONS differ in code:")
        for f in changed_files:
            if not f.endswith(".go"):
                continue
            fd = func_diff(snaps[A][f], snaps[B][f], renames)
            bits = []
            if fd["changed"]:
                bits.append("changed " + ", ".join(fd["changed"]))
            if fd["only_a"]:
                bits.append(f"{A.name}-only " + ", ".join(fd["only_a"]))
            if fd["only_b"]:
                bits.append(f"{B.name}-only " + ", ".join(fd["only_b"]))
            if fd["residue_differs"]:
                bits.append(f"OUTSIDE any func ({fd['residue_delta']:+d} chars: imports, type "
                            f"or var decls)")
            print(f"    {f:<{width}} {len(fd['changed'])} of {fd['n_a']} func(s) differ"
                  + (f" — {' · '.join(bits)}" if bits else " — none, and nothing outside them "
                                                           "either: comments/strings only"))
            fn_collateral += [c for c in fd["changed"] if c not in renames]
            if renames and fd["renamed_body_changed"]:
                print(f"      (the RENAMED function's own body also changed)")
        print(f"\n  FUNCTION-LEVEL COLLATERAL: {len(fn_collateral)}"
              + (f" — {sorted(set(fn_collateral))}" if fn_collateral else " — none"))
        if fn_collateral and target is not None and not collateral(diff_code, target):
            print("  ⚠ THE FILE-LEVEL VERDICT WAS A FALSE NULL. Every differing file is the")
            print("    target, so file granularity reports COLLATERAL 0, but a function the")
            print("    edit never mentions wrote different code. Report the function count.")
    # RENAME-ONLY. A declared rename IS a code difference by any honest classifier, so a pure
    # rename shows up as "CODE 1, the target" and looks like a landed edit with no collateral.
    # Neutralising the rename separates "the edit, and nothing else" from "the edit, and more".
    if renames and diff_code:
        survivors = [f for f in diff_code
                     if neutralise(snaps[A][f], renames) != neutralise(snaps[B][f], renames)]
        if not survivors:
            print(f"\n  ✅ RENAME-ONLY: every CODE difference IS the declared rename. Neutralise "
                  f"it and all {len(diff_code)} file(s) are code-identical.")
            print("     No program changed anywhere. This is a CONFIRMED null at code level — "
                  "the strongest null this")
            print("     tool can report, and distinct from a file-level null, which only says "
                  "no other FILE moved.")
        else:
            print(f"\n  the rename does NOT account for everything: {len(survivors)} file(s) "
                  f"still differ in code after neutralising it — {survivors}")
        # THE CATEGORY LINE. Added 30 July 16:15, and it exists because this tool has been
        # printing BOTH measures since it was written while its reader took one and drew
        # conclusions as if it were the other. On six consecutive arms the two agreed, so nothing
        # forced the distinction; the seventh disagreed maximally — collateral 0 with the renamed
        # function's own body rewritten — and it overturned a by-spec conclusion drawn from the six.
        #
        #   RENAME-ONLY  nothing differs but the declared name
        #   LOCAL        the renamed function's own body differs; no other file or function moves
        #   COLLATERAL   a file or function the edit does not name wrote different code
        #
        # The three are disjoint and exhaustive for a rename arm, which the old perturbed/null
        # binary was not. A pre-registration that says "perturbs" without naming which of these it
        # means is unscorable, and one was.
        n_coll = len(fn_collateral)
        if n_coll:
            cat = "COLLATERAL"
        elif survivors:
            cat = "LOCAL"
        else:
            cat = "RENAME-ONLY"
        print(f"  CATEGORY: {cat}   (collateral {n_coll} · beyond-rename "
              f"{'YES' if survivors else 'no'})")
    # A prose difference in a file the edit does not name is not a program change, but it is not
    # nothing either: it is the edit propagating as WORDING. Worth its own line, because the
    # series' CODE/PROSE split otherwise files it under "no difference".
    prose_elsewhere = [f for f, k in r["rows"] if k == "PROSE" and f != target]
    if prose_elsewhere:
        print(f"  ⚠ PROSE-ONLY difference in {len(prose_elsewhere)} file(s) the edit does not "
              f"name: {prose_elsewhere}")
        print("    No code changed there, but the wording did — the edit propagated as text. "
              "Not collateral; not nothing.")
    if counts.get("CODE"):
        print("  CODE means the two draws wrote different PROGRAMS, not different wording.")
    elif counts.get("PROSE"):
        print("  Only PROSE differs: same program, different comments or message strings.")
    else:
        print("  Byte-identical as drawn.")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(main(sys.argv[1:]))
