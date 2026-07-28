#!/usr/bin/env python3
"""Does a TEST entry demand a guard that no IMPLEMENTATION entry promises?

WHY. taskapipro's config_test.go entry says:

    "TestValidateRejectsZeroDefaultPageSize ... ZERO is the case, not a negative number:
     the guard is `DefaultPageSize <= 0`"

and its config.go entry — the one that writes the code — says Validate returns an error
"if Addr is empty or MaxPageSize < DefaultPageSize". That is all. The zero guard is named
ONLY in the entry that checks it, never in the entry that builds it.

When I added that closure I added the test requirement and never added the matching
implementation requirement. Measured across four draws: three inferred the missing guard
from the test entry anyway, and the fourth did not — it spent its entire six-round fix
budget failing a test the implementation had never been asked to satisfy, on a spec whose
two entries cannot both be honoured by reading each one at a time.

This is the same shape as the Create(t Task) error contradiction found the day before: two
entries, each locally coherent, jointly unsatisfiable. That one was a TYPE disagreement and
spec-lint rule 5 now catches it. This one is a MISSING PROMISE, and nothing checked it.

    A behaviour a test demands has to be promised in the entry that WRITES the code,
    not only in the entry that CHECKS it. The model reads one entry at a time.

WHAT IT LOOKS FOR. Backticked code fragments containing a COMPARISON, appearing in a
*_test.go entry, absent from every non-test entry of the same spec. Backticks are how these
specs quote code; a comparison is how they write a guard. Fragments without a comparison are
ignored on purpose — `{"title":`, `[]T{}`, helper names and literal bodies are legitimately
test-only and are most of what is in there.

A hit is a CANDIDATE. A test may quote a guard as EXPLANATION of a behaviour the
implementation entry describes in prose ("clamps negatives to zero"), and that is fine — it
just needs a read to tell apart from a promise nobody made.

    python _promise_gap.py            # every spec
    python _promise_gap.py specs/x.yaml
    python _promise_gap.py --self-test
"""
from __future__ import annotations

import pathlib
import re
import sys

ENTRY_RE = re.compile(r"^\s*-\s*path:\s*(\S+)\s*$", re.M)
BACKTICK_RE = re.compile(r"`([^`]+)`")
COMPARISON_RE = re.compile(r"(<=|>=|==|!=|<|>)")


def entries(text: str) -> list[tuple[str, str]]:
    out, marks = [], list(ENTRY_RE.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1), text[m.end():end]))
    return out


def norm(s: str) -> str:
    """Whitespace-insensitive, so `DefaultPageSize <= 0` matches `DefaultPageSize<=0`."""
    return re.sub(r"\s+", "", s)


def audit(spec_text: str) -> list[dict]:
    ents = entries(spec_text)
    impl = "".join(norm(b) for p, b in ents if not p.endswith("_test.go"))
    rows = []
    for path, body in ents:
        if not path.endswith("_test.go"):
            continue
        seen = set()
        for frag in BACKTICK_RE.findall(body):
            if not COMPARISON_RE.search(frag):
                continue
            # A GUARD IS AN EXPRESSION, NOT A CODE BLOCK. These test entries quote whole
            # helper bodies and table loops in backticks — `for _, n := range []uint64{...}
            # { ... if got != n { t.Errorf(...) } }` — and every one of them contains a
            # comparison. Flagging those made the first run report eleven candidates of
            # which nine were quoted test machinery, which is the shape of a tool that has
            # stopped discriminating. A guard has no braces, no statement separator and no
            # line break; `DefaultPageSize <= 0` survives this, a helper body does not.
            if any(c in frag for c in "{};") or "\n" in frag:
                continue
            n = norm(frag)
            if n in seen:
                continue
            seen.add(n)
            if n not in impl:
                rows.append({"test_entry": path, "guard": frag.strip()})
    return rows


def self_test() -> int:
    fails = []
    gap = """
  - path: config.go
    purpose: >-
      Validate() returns an error if Addr is empty or MaxPageSize < DefaultPageSize.
  - path: config_test.go
    purpose: >-
      TestRejectsZero: the guard is `DefaultPageSize <= 0`, so zero must be rejected.
"""
    rows = audit(gap)
    if len(rows) != 1 or rows[0]["guard"] != "DefaultPageSize <= 0":
        fails.append(f"the guard named only in the test entry must be reported: {rows}")

    kept = """
  - path: config.go
    purpose: >-
      Validate() errors when `DefaultPageSize <= 0` or MaxPageSize < DefaultPageSize.
  - path: config_test.go
    purpose: >-
      TestRejectsZero: the guard is `DefaultPageSize<=0`, so zero must be rejected.
"""
    # REJECT-NOTHING PIN 1: promised in the impl entry, quoted in the test entry, differing
    # only in whitespace. Reporting this makes every closure look like a defect.
    if audit(kept):
        fails.append(f"a guard the implementation entry DOES promise must not be "
                     f"reported: {audit(kept)}")

    # REJECT-NOTHING PIN 2: test entries are full of backticked fragments that are not
    # guards at all. Without the comparison filter this tool reports the whole corpus.
    noise = """
  - path: h.go
    purpose: >-
      Handler writes JSON.
  - path: h_test.go
    purpose: >-
      TestMalformed: POST truncated bytes like `{"title":` -> 400, and assert
      `strings.TrimSpace(rec.Body.String())` is exactly `[]`.
"""
    if audit(noise):
        fails.append(f"a backticked fragment with no comparison is not a guard: {audit(noise)}")

    # The same guard quoted twice in one entry is one candidate, not two.
    twice = """
  - path: a.go
    purpose: >-
      Does a thing.
  - path: a_test.go
    purpose: >-
      the guard is `x < 0` and again `x < 0`.
"""
    if len(audit(twice)) != 1:
        fails.append(f"a repeated guard is one row: {audit(twice)}")

    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — names the unpromised guard, silent on promised ones and "
                           "on non-guards"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    targets = [pathlib.Path(a) for a in sys.argv[1:] if not a.startswith("-")]
    if not targets:
        targets = sorted((pathlib.Path(__file__).resolve().parent / "specs").glob("*.yaml"))
    flagged = 0
    for spec in targets:
        rows = audit(spec.read_text())
        if not rows:
            continue
        print(f"\n{spec.name}")
        for r in rows:
            flagged += 1
            print(f"   {r['test_entry']}")
            print(f"      demands `{r['guard']}` — no implementation entry mentions it")
    print(f"\n{flagged} guard(s) named only in a test entry, across {len(targets)} spec(s)")
    print("A CANDIDATE, not a verdict: a test may quote a guard as explanation of something\n"
          "the implementation entry states in prose. What it must not be is the only place\n"
          "the behaviour is asked for — the model reads one entry at a time.")
