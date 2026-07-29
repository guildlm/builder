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

import json
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
    """Elements in a slice literal: depth-0 comma-separated segments that are NON-EMPTY.

    COUNTING COMMAS AND ADDING ONE IS WRONG IN GO, and this returned 4 for a three-element
    literal until 15:07 on 29 July. Go permits — and gofmt REQUIRES — a trailing comma in a
    multi-line composite literal:

        []string{
            `{"id":"3","name":"c"}`,
            `{"id":"1","name":"a"}`,
            `{"id":"2","name":"b"}`,      <- this one
        }

    Three elements, three depth-0 commas. commas+1 gives four. Splitting and dropping empty
    segments gives three, and handles a single-line literal with no trailing comma equally.

    Caught by the tool disagreeing with the source: it reported seeds=4 against an assertion
    of 3 on a tree that was GREEN, and a green tree whose witness "cannot pass" is a
    contradiction that has to be one of the two being wrong. It was the instrument.

    The self-test did not catch it because the planted literal had no trailing comma — the
    fixture was written by hand, and by hand one does not add one. Real gofmt'd Go always
    does. A fixture that is not formatted the way the corpus is formatted tests a language
    nobody writes.
    """
    depth, segs, cur = 0, [], ""
    for ch in items:
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        if ch == "," and depth == 0:
            segs.append(cur)
            cur = ""
        else:
            cur += ch
    segs.append(cur)
    return sum(1 for seg in segs if seg.strip())


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


FIXING = re.compile(r"^\[guildlm-build\]\s+fixing (\S+?\.go)(?: \(widened in\))?\s*$", re.M)
DETERMINISTIC = re.compile(r"^\[guildlm-build\]\s+deterministic fix in (\S+?\.go)\s*$", re.M)
DRAINED = re.compile(r"^\[guildlm-build\]\s+rebuilt a request that was served twice "
                     r"\(drained body\) in (\S+?\.go)\s*$", re.M)


def provenance(log_text: str) -> dict[str, dict]:
    """Which files a draw REWROTE after generating them, from the build log.

    WHY A TREE-READING TOOL NEEDS THIS, and it cost two retractions on 29 July before it was
    built. This tool reads a tree on disk and prints CANNOT-PASS / CANNOT-FAIL / DISCRIMINATES
    with total confidence. A tree on disk is the POST-REPAIR tree. If the fix loop called
    `fixing internal/api/projects_test.go` three times, the numbers here describe what the
    LOOP left behind, not what the draw produced — and two draws being compared can differ
    entirely in how much repair they absorbed:

        chain4   projects_test.go: one DETERMINISTIC fix, converged. Numbers ~= as-drawn.
        v5       projects_test.go: drained-body rebuild + `fixing` in rounds 1, 2 and 5, and
                 the tree never compiled so no test ever RAN. Numbers are post-3-rewrites.

    Comparing those two and attributing the difference to a spec edit is the error, and it
    was made twice in one file. Deterministic fixes are goimports-class and do not rewrite
    assertions or seeding, so they do NOT spoil provenance; a model `fixing` call rewrites
    whatever it likes, so it does.

    Returns {relpath: {"model": n, "deterministic": n, "drained": n}}.
    """
    out: dict[str, dict] = {}
    for kind, rx in (("model", FIXING), ("deterministic", DETERMINISTIC), ("drained", DRAINED)):
        for path in rx.findall(log_text):
            out.setdefault(path, {"model": 0, "deterministic": 0, "drained": 0})[kind] += 1
    return out


def provenance_note(rel: str, prov: dict[str, dict] | None) -> str:
    """The qualifier printed beside a verdict. Empty only when provenance is genuinely clean."""
    if prov is None:
        return ""
    p = prov.get(rel)
    if p is None:
        return "  [as-drawn: untouched]"
    if p["model"]:
        extra = " +drained-body rebuild" if p["drained"] else ""
        return (f"  ⚠ POST-REPAIR: {p['model']} model rewrite(s){extra} — this verdict "
                f"describes the LOOP's file, not the draw's")
    if p["drained"]:
        return "  [drained-body rebuild only — a request was replaced, assertions untouched]"
    return "  [as-drawn: deterministic fixes only]"


def verdict(seeded: int, bound: int) -> str:
    if seeded < bound:
        return "CANNOT-PASS"
    if seeded == bound:
        return "CANNOT-FAIL"
    return "DISCRIMINATES"


def audit_sources(files: dict) -> list[tuple]:
    """The same audit over {relative_path: source} instead of a directory.

    EXISTS SO THE PRE-REPAIR SNAPSHOT CAN BE AUDITED. `<out>/.pre-fix.json` holds exactly this
    mapping — every file as the model wrote it, before the fix loop touched anything. Reading
    a tree can only ever answer "what did the LOOP leave behind"; two claims were retracted on
    29 July for not distinguishing that from "what did the DRAW produce".
    """
    rows = []
    for rel in sorted(files):
        if not rel.endswith("_test.go"):
            continue
        text = files[rel]
        for name, body in bodies(text):
            r = ROUTER.search(body)
            a = ASSERT_LEN.search(body)
            if not (r and a):
                continue
            dflt, mx = int(r.group(1)), int(r.group(2))
            bound = int(a.group(2))
            probing_cap = "limit=" in body
            knob = mx if probing_cap else dflt
            note = "" if knob == bound else f"  ⚠ asserts {bound} but the knob is {knob}"
            rows.append((rel, name, dflt, mx, seeds(body), bound,
                         verdict(seeds(body), bound), note))
    return rows


def compare_as_drawn(post: list[tuple], ad: list[tuple]) -> list[tuple[str, str]]:
    """Witnesses whose seed/assert numbers the FIX LOOP moved, as (name, description).

    THE WHOLE POINT OF THE SNAPSHOT, in one function. Empty means the tree's numbers ARE the
    draw's numbers and can be reported as such. Non-empty means they are not, and every
    comparison that treats them as the draw's is the error retracted twice on 29 July.

    A witness present as-drawn and ABSENT afterwards is reported too — the loop deleting a
    test is the drained-body gate's failure mode one layer up, and it is invisible in a
    verdict list that only walks what survived.
    """
    byname = {r[1]: r for r in post}
    moved = []
    for rel, name, dflt, mx, sd, bound, v, note in ad:
        cur = byname.get(name)
        if cur is None:
            moved.append((name, f"as-drawn seeds={sd} asserts={bound} ({v}) — "
                                f"NOT PRESENT after repair"))
        elif (cur[4], cur[5]) != (sd, bound):
            moved.append((name, f"as-drawn seeds={sd} asserts={bound} ({v})  ->  "
                                f"post-repair seeds={cur[4]} asserts={cur[5]} ({cur[6]})"))
    return moved


def as_drawn(tree: pathlib.Path) -> list[tuple] | None:
    """Audit the pre-repair snapshot, or None if this draw predates it."""
    snap = tree / ".pre-fix.json"
    if not snap.is_file():
        return None
    return audit_sources(json.loads(snap.read_text()))


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
    # THE TRAILING COMMA — gofmt requires one in a multi-line literal, every real Go file
    # has it, and counting commas+1 turns three elements into four.
    if literal_len('\n\t`{"id":"3"}`,\n\t`{"id":"1"}`,\n\t`{"id":"2"}`,\n') != 3:
        fails.append("a gofmt trailing comma must not add a phantom element")
    # THE SNAPSHOT PATH. audit_sources must agree with audit on the same content, and
    # compare_as_drawn must flag a moved number and a deleted test — the two ways the loop
    # can make a tree lie about its draw.
    src = ('func TestPaging(t *testing.T) {\n'
           '\th := newRouterWithPaging(2, 100)\n'
           '\treq1 := httptest.NewRequest("POST", "/x", nil)\n'
           '\treq2 := httptest.NewRequest("POST", "/x", nil)\n'
           '\treq3 := httptest.NewRequest("POST", "/x", nil)\n'
           '\tif len(got) != 2 {\n\t\tt.Errorf("x")\n\t}\n}\n')
    ad_rows = audit_sources({"api_test.go": src})
    if len(ad_rows) != 1 or ad_rows[0][4] != 3 or ad_rows[0][6] != "DISCRIMINATES":
        fails.append(f"audit_sources must audit a dict exactly as audit does; got {ad_rows}")
    if audit_sources({"api.go": src}):
        fails.append("only _test.go files are audited")
    weakened = audit_sources({"api_test.go": src.replace(
        '\treq2 := httptest.NewRequest("POST", "/x", nil)\n', "").replace(
        '\treq3 := httptest.NewRequest("POST", "/x", nil)\n', "")})
    moved = compare_as_drawn(weakened, ad_rows)
    if len(moved) != 1 or "3" not in moved[0][1]:
        fails.append(f"a loop that drops two seeds must be flagged with both numbers; {moved}")
    if compare_as_drawn(ad_rows, ad_rows):
        fails.append("identical as-drawn and post-repair must report NOTHING — otherwise the "
                     "warning cries wolf on every clean draw and gets ignored")
    if len(compare_as_drawn([], ad_rows)) != 1 or "NOT PRESENT" not in compare_as_drawn([], ad_rows)[0][1]:
        fails.append("a test the loop DELETED must be reported, not silently skipped")

    # PROVENANCE — the check that would have stopped two retractions on 29 July.
    log = (
        "[guildlm-build]   deterministic fix in internal/api/router_test.go\n"
        "[guildlm-build]   rebuilt a request that was served twice (drained body) in internal/api/projects_test.go\n"
        "[guildlm-build]   fixing internal/api/projects_test.go\n"
        "[guildlm-build]   fixing internal/api/projects_test.go\n"
        "[guildlm-build]   fixing internal/api/projects.go (widened in)\n"
    )
    prov = provenance(log)
    if prov.get("internal/api/projects_test.go", {}).get("model") != 2:
        fails.append("two `fixing` lines for one file must count 2 model rewrites")
    if prov.get("internal/api/projects_test.go", {}).get("drained") != 1:
        fails.append("a drained-body rebuild must be counted separately from a model rewrite")
    if prov.get("internal/api/projects.go", {}).get("model") != 1:
        fails.append("a `(widened in)` suffix must not stop the path from being recognised")
    if prov.get("internal/api/router_test.go", {}).get("deterministic") != 1:
        fails.append("a deterministic fix must be counted, and separately")
    if "POST-REPAIR" not in provenance_note("internal/api/projects_test.go", prov):
        fails.append("a model-rewritten file must be flagged POST-REPAIR")
    if "POST-REPAIR" in provenance_note("internal/api/router_test.go", prov):
        fails.append("deterministic fixes alone must NOT be flagged post-repair — chain4's "
                     "tree is the only clean provenance in the whole comparison")
    if "untouched" not in provenance_note("internal/api/nothing.go", prov):
        fails.append("a file the log never mentions is as-drawn and must say so")
    if provenance_note("anything", None) != "":
        fails.append("with no log supplied the tool must add no provenance claim at all")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — loop seeding counted, straight-line counted, all three "
                           "verdicts separated, and the snapshot path flags a moved "
                           "or deleted witness while staying silent on a clean draw"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    flags = [a for a in sys.argv[1:] if a.startswith("-")]
    unknown = [a for a in flags if not a.startswith("--log=")]
    if unknown:
        raise SystemExit(f"REFUSING: unknown flag(s) {' '.join(unknown)}. "
                         f"Takes --self-test or --log=<build log>.")
    prov = None
    for a in flags:
        p = pathlib.Path(a.split("=", 1)[1])
        if not p.is_file():
            raise SystemExit(f"REFUSING: --log={p} is not a file. Provenance unchecked is a "
                             f"worse state than provenance absent, because the rows still print.")
        prov = provenance(p.read_text(errors="ignore"))
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
            pn = provenance_note(str(rel), prov)
            if pn:
                print(f"   {'':14} {pn.strip()}")
        bad = [r for r in rows if r[6] != "DISCRIMINATES"]
        print(f"   -> {len(rows) - len(bad)} of {len(rows)} witnesses can discriminate")
        # AS-DRAWN, when the draw carries a snapshot. This is the number the retracted claims
        # needed: what the MODEL wrote, as opposed to what the fix loop left behind.
        ad = as_drawn(t)
        if ad is None:
            print("   (no .pre-fix.json — this draw predates the snapshot, so its AS-DRAWN "
                  "values are not recoverable)")
        else:
            moved = compare_as_drawn(rows, ad)
            if moved:
                print("   ⚠ THE FIX LOOP CHANGED THESE WITNESSES — the tree's numbers are NOT "
                      "the draw's:")
                for name, msg in moved:
                    print(f"      {name:<48} {msg}")
            else:
                print(f"   as-drawn == post-repair for all {len(ad)} witness(es): the fix loop "
                      f"did not move these numbers")
    if prov is None:
        # SAY IT EVERY TIME. The two retractions of 29 July both came from comparing a
        # post-repair tree to a near-as-drawn one, and nothing in this tool's output
        # distinguished them. A verdict with unknown provenance is not a verdict about a draw.
        print("\n⚠ PROVENANCE UNCHECKED — these numbers are read off the tree ON DISK, which is\n"
              "  the POST-REPAIR tree. If the fix loop rewrote a test file, they describe what\n"
              "  the LOOP left behind, not what the draw produced. Pass --log=<build log> to\n"
              "  find out. Two claims were retracted on 29 July for exactly this.")
