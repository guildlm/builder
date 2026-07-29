#!/usr/bin/env python3
"""Can a paging witness actually discriminate? Count the items it seeds against the bound.

    python _twin_witness.py generated/taskapipro-v5
    python _twin_witness.py --self-test

WHY THIS EXISTS. A paging test has three numbers — the page size the router is built with,
the number of items it seeds, and the length it asserts — and the test is only a witness
when they stand in one particular relation. Two draws of taskapipro got the router
arguments right, the assertion right, and the ITEM COUNT wrong, in opposite directions,
and neither a green suite nor a mutation sweep says so:

    seeds < bound   the test CANNOT PASS. It fails against a correct handler.
    seeds == bound  the test CANNOT FAIL. A handler that ignores the page size entirely
                    returns all `seeds` items, which is also `bound`, which is what a
                    correct handler returns. No input separates them.
    seeds > bound   it DISCRIMINATES. This is the only case worth writing.

The rule is the same one the specs argue for in prose — "the witness has to sit ON the
boundary, not past it" — and prose measurably did not secure it (see
RESULT-prose-bought-the-assertion-and-not-the-setup.txt). This counts it instead.

COUNTING SEEDS IS THE WHOLE DIFFICULTY, AND AN AD-HOC VERSION OF THIS GOT IT WRONG.
A grep for httptest.NewRequest("POST" reported taskflow's TestListSorted as seeding ONE
item. It seeds THREE — one request inside a `for _, body := range []string{...}` over a
three-element literal. The grep was right about its query and wrong about the world, which
is this session's recurring failure. So a POST inside a range-over-literal counts as the
literal's length, and the self-test plants exactly that case; without it this tool would
report the same wrong number in the same confident format.
"""
from __future__ import annotations

import pathlib
import re
import sys

FUNC = re.compile(r"^func (Test\w+)\(t \*testing\.T\) \{$", re.M)
ROUTER = re.compile(r"newRouterWithPaging\((\d+),\s*(\d+)\)")
POST = re.compile(r'httptest\.NewRequest\(\s*(?:"POST"|http\.MethodPost)')
ASSERT_LEN = re.compile(r"len\((\w+)\)\s*!=\s*(\d+)")
# `for _, x := range []string{ "a", "b", "c" }` — count the top-level commas + 1. Only
# literal slices; a range over a variable is not countable here and is reported as unknown
# rather than guessed, because a guess is what produced the wrong number the first time.
RANGE_LIT = re.compile(r"for\s+.*:=\s*range\s*\[\]\w+\{(.*?)\}\s*\{", re.S)


def bodies(text: str) -> list[tuple[str, str]]:
    """(name, body) for each top-level test function, body ending at the first ^}."""
    out = []
    for m in FUNC.finditer(text):
        start = m.end()
        end = text.find("\n}\n", start)
        out.append((m.group(1), text[start:end if end != -1 else len(text)]))
    return out


def literal_len(items: str) -> int:
    """Elements in a slice literal, counting only commas at depth 0."""
    depth, n = 0, 1
    for ch in items:
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        elif ch == "," and depth == 0:
            n += 1
    return n if items.strip() else 0


def seeds(body: str) -> int:
    """How many items this test actually puts in the store."""
    total = 0
    consumed = []
    for m in RANGE_LIT.finditer(body):
        block_start = m.end()
        # The loop body runs to the matching close brace; approximate by the next `\n\t}`.
        close = body.find("\n\t}", block_start)
        block = body[block_start:close if close != -1 else len(body)]
        posts_in_loop = len(POST.findall(block))
        if posts_in_loop:
            total += posts_in_loop * literal_len(m.group(1))
            consumed.append((block_start, close if close != -1 else len(body)))
    # POSTs outside any counted loop body.
    for m in POST.finditer(body):
        if not any(s <= m.start() < e for s, e in consumed):
            total += 1
    return total


def verdict(seeded: int, bound: int) -> str:
    if seeded < bound:
        return "CANNOT-PASS"
    if seeded == bound:
        return "CANNOT-FAIL"
    return "DISCRIMINATES"


def audit(tree: pathlib.Path) -> list[tuple]:
    rows = []
    for f in sorted(tree.rglob("*_test.go")):
        text = f.read_text()
        for name, body in bodies(text):
            r = ROUTER.search(body)
            a = ASSERT_LEN.search(body)
            if not (r and a):
                continue
            dflt, mx = int(r.group(1)), int(r.group(2))
            bound = int(a.group(2))
            # Which knob this test is aimed at: a request carrying ?limit= is probing the
            # CAP, anything else is probing the DEFAULT. The bound asserted should equal
            # that knob; if it does not, the test is not measuring what its name says.
            probing_cap = "limit=" in body
            knob = mx if probing_cap else dflt
            note = "" if knob == bound else f"  ⚠ asserts {bound} but the knob is {knob}"
            rows.append((f.relative_to(tree), name, dflt, mx, seeds(body), bound,
                         verdict(seeds(body), bound), note))
    return rows


def self_test() -> int:
    fails = []
    # THE LOOP CASE — the one an ad-hoc grep got wrong. Three items, one POST statement.
    loop_src = '''func TestLoopSeeded(t *testing.T) {
	h := newRouterWithPaging(2, 100)
	for _, body := range []string{`{"id":"3"}`, `{"id":"1"}`, `{"id":"2"}`} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(body)))
	}
	if len(all) != 2 {
		t.Errorf("x")
	}
}
'''
    (name, body), = bodies(loop_src)
    if seeds(body) != 3:
        fails.append(f"a POST inside range-over-3-literal must count 3, got {seeds(body)}")
    # Straight-line POSTs.
    flat = '''func TestFlat(t *testing.T) {
	h := newRouterWithPaging(20, 2)
	req1 := httptest.NewRequest("POST", "/tasks", nil)
	req2 := httptest.NewRequest("POST", "/tasks", nil)
	if len(resp) != 2 {
		t.Errorf("x")
	}
}
'''
    (_, fbody), = bodies(flat)
    if seeds(fbody) != 2:
        fails.append(f"two straight-line POSTs must count 2, got {seeds(fbody)}")
    # The three verdicts.
    for s, b, want in ((1, 2, "CANNOT-PASS"), (2, 2, "CANNOT-FAIL"), (3, 2, "DISCRIMINATES")):
        if verdict(s, b) != want:
            fails.append(f"seeds={s} bound={b} should be {want}, got {verdict(s, b)}")
    # A slice literal with a nested brace must not over-count.
    if literal_len('`{"id":"1"}`, `{"id":"2"}`') != 2:
        fails.append("commas inside braces must not be counted as separators")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — loop seeding counted, straight-line counted, "
                           "and all three verdicts separated"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    targets = [pathlib.Path(a) for a in sys.argv[1:] if not a.startswith("-")]
    if not targets:
        raise SystemExit(__doc__)
    for t in targets:
        print(f"\n{t.name}")
        rows = audit(t)
        if not rows:
            print("   no paging witnesses found (no newRouterWithPaging + len!=N pair)")
        for rel, name, dflt, mx, sd, bound, v, note in rows:
            print(f"   {v:<14} {name:<48} router({dflt},{mx}) seeds={sd} asserts={bound}{note}")
        bad = [r for r in rows if r[6] != "DISCRIMINATES"]
        print(f"   -> {len(rows) - len(bad)} of {len(rows)} witnesses can discriminate")
