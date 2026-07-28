#!/usr/bin/env python3
"""Which registered routes does no test ever REQUEST?

WHY. Eight of the nineteen real holes in this corpus are MIRRORS: a guard whose identical
twin on a neighbouring route has a test. taskflow's is the sharpest — the spec promises
"Delete (204 or 404)" and names TestDelete "DELETE it -> 204, then GET it -> 404". That test
asserts a 404, from GET. Delete's own 404 was never requested by anything. And taskapi's
projects_test.go entry says outright that until it was written, List and Delete "were never
called once".

Every one of those was found by hand, after a mutation survived, one row at a time. But the
question underneath them is not about mutations at all and can be asked directly of the
source: does any test send this METHOD to this PATH? A route nobody requests is not one
undefended assertion — it is every promise on that route at once, and no mutation on a line
inside it can be caught by anything.

This is the reachability axis again, asked at the door rather than at the line. Same axis as
the seventeen dead 500-else branches (a line no test executes) and the dead config fields (a
value nothing reads); a route nobody calls is the coarsest version and the cheapest to see.

WHAT A HIT IS. A CANDIDATE, not a verdict. Health endpoints are routinely registered and
rarely asserted, and that is a judgement call, not a defect. What a hit cannot mean is
"covered" — whatever the suite says about that resource, this door has never been opened.

    python _route_coverage.py                 # every -v4 artifact
    python _route_coverage.py generated/x     # one tree
    python _route_coverage.py --self-test
"""
from __future__ import annotations

import pathlib
import re
import sys

# `"GET /tasks/{id}"` — Go 1.22 method+pattern registration, which every HTTP artifact here
# uses. Bare patterns are deliberately NOT matched: a route registered without a method
# answers every method, so "which method is untested" is not a question it can be asked.
ROUTE_RE = re.compile(r'"((?:GET|POST|PUT|PATCH|DELETE) /[^"]*)"')
# A METHOD LITERAL NEXT TO A PATH LITERAL, ANYWHERE IN A TEST FILE — deliberately not
# anchored to NewRequest.
#
# The first version anchored on `NewRequest(...)` and reported usersapi as 5 routes, 5 never
# requested, which is false about a suite that POSTs, GETs and DELETEs users throughout. Both
# usersapi and ratelimit funnel every call through a helper:
#
#     r = httptest.NewRequest(method, path, ...)      // <- variables, no literal here
#     ...
#     do(h, "POST", "/users", body)                   // <- the literals are at the CALL SITE
#
# So the anchor was the bug. What identifies a request is the PAIR, wherever it appears, and
# a table-driven case listing {"POST", "/users"} is a request by any reading.
#
# Note the failure DIRECTION, because it is the opposite of the stale allowlist fixed earlier
# today: that one failed toward "nothing to see here", this one failed toward INVENTING
# holes. Only the reject-nothing number caught it — 5 of 5 flagged is not a finding, it is a
# tool that has stopped discriminating, and a tool that reports everything reports nothing.
# FOUR SHAPES, because the corpus writes requests four ways and three of them were reported
# as holes by the first two drafts of this tool:
#
#   httptest.NewRequest("DELETE", "/tasks/1", nil)      literal method, literal path
#   httptest.NewRequest(http.MethodGet, "/health", nil) constant method
#   http.NewRequest(http.MethodPut, srv.URL+"/kv/a", …) path CONCATENATED to a base URL
#   http.Get(srv.URL + "/kv/missing")                   method is the FUNCTION NAME
#
# and a fifth that carries no method at all:
#
#   hit(mux, "/ping", "clientA")                        helper fixes the method internally
#
# The path may be preceded by anything ending in `+`, and the method may be a literal, a
# constant, or the name of the helper function itself.
METHOD_CONST = {"MethodGet": "GET", "MethodPost": "POST", "MethodPut": "PUT",
                "MethodPatch": "PATCH", "MethodDelete": "DELETE"}
_PATH = r'(?:[\w.]+\s*\+\s*)?"(/[^"]*)"'
REQ_RE = re.compile(r'"(GET|POST|PUT|PATCH|DELETE)"\s*,\s*' + _PATH)
REQ_CONST_RE = re.compile(r'http\.(Method\w+)\s*,\s*' + _PATH)
# http.Get / http.Post / http.Head — the stdlib helpers whose name IS the method.
REQ_FUNC_RE = re.compile(r'\bhttp\.(Get|Post|Head)\(\s*' + _PATH)
# ANY path literal in a test file. Weak evidence: it says the door was named, not which
# method knocked. Reported as its own state rather than folded into either verdict, because
# "I could not attribute a method" and "no test requests this" are different claims and only
# one of them is a finding.
ANY_PATH_RE = re.compile(r'"(/[^"]*)"')


def pattern_to_re(path: str) -> re.Pattern:
    """`/tasks/{id}` matches `/tasks/1`; `/tasks` matches `/tasks` and `/tasks?limit=1`."""
    parts = [r"[^/]+" if p.startswith("{") else re.escape(p) for p in path.split("/")]
    return re.compile("^" + "/".join(parts) + r"(\?.*)?$")


def registered(tree: pathlib.Path) -> list[str]:
    out: set[str] = set()
    for p in sorted(tree.rglob("*.go")):
        if p.name.endswith("_test.go"):
            continue
        out |= set(ROUTE_RE.findall(p.read_text(errors="replace")))
    return sorted(out)


def requested(tree: pathlib.Path) -> tuple[list[tuple[str, str]], list[str]]:
    """(method, path) pairs where the method is knowable, and every path literal seen."""
    pairs: list[tuple[str, str]] = []
    paths: list[str] = []
    for p in sorted(tree.rglob("*_test.go")):
        text = p.read_text(errors="replace")
        pairs += REQ_RE.findall(text)
        pairs += [(METHOD_CONST[c], path) for c, path in REQ_CONST_RE.findall(text)]
        pairs += [(fn.upper(), path) for fn, path in REQ_FUNC_RE.findall(text)]
        paths += ANY_PATH_RE.findall(text)
    return pairs, paths


def audit_tree(tree: pathlib.Path) -> list[dict]:
    pairs, paths = requested(tree)
    rows = []
    for route in registered(tree):
        method, path = route.split(" ", 1)
        pat = pattern_to_re(path)
        hits = [p for m, p in pairs if m == method and pat.match(p)]
        # Only asked when the method could not be attributed — a path seen without a method
        # is weaker evidence, and calling it a hit would let a suite that only ever GETs a
        # resource certify its DELETE.
        seen = [p for p in paths if pat.match(p)] if not hits else []
        rows.append({"route": route, "hits": len(hits), "path_seen": len(seen),
                     "examples": sorted(set(hits))[:2]})
    return rows


def self_test() -> int:
    import tempfile
    fails = []
    if not pattern_to_re("/tasks/{id}").match("/tasks/1"):
        fails.append("a {param} segment must match a concrete id")
    if pattern_to_re("/tasks/{id}").match("/tasks"):
        fails.append("/tasks/{id} must NOT match the collection path")
    if not pattern_to_re("/tasks").match("/tasks?limit=1&offset=-1"):
        fails.append("a query string must not hide a request to the collection — the "
                     "negative-offset tests are exactly this shape")
    if pattern_to_re("/tasks").match("/tasks/1"):
        fails.append("the collection must NOT swallow a request to a single item, or a "
                     "route with only collection tests reads as covered")

    with tempfile.TemporaryDirectory() as d:
        tree = pathlib.Path(d)
        (tree / "router.go").write_text(
            'package main\nfunc R() {\n'
            '\tmux.HandleFunc("GET /tasks", list)\n'
            '\tmux.HandleFunc("DELETE /tasks/{id}", del)\n'
            '\tmux.HandleFunc("GET /health", hz)\n}\n')
        # GETs the collection and DELETEs nothing: the DELETE route is the planted hole, and
        # /health is reached only through the http.MethodGet constant form.
        (tree / "router_test.go").write_text(
            'package main\n'
            '// /tasks goes through a HELPER whose NewRequest sees only variables — the shape\n'
            '// that made the first version of this tool call usersapi 5-for-5 uncovered.\n'
            'func do(method, path string) { httptest.NewRequest(method, path, nil) }\n'
            'func TestX(t *testing.T) {\n'
            '\tdo("GET", "/tasks")\n'
            '\thttptest.NewRequest(http.MethodGet, "/health", nil)\n}\n')
        rows = {r["route"]: r for r in audit_tree(tree)}
        if set(rows) != {"GET /tasks", "DELETE /tasks/{id}", "GET /health"}:
            fails.append(f"all three registrations must be audited: {sorted(rows)}")
        if rows.get("DELETE /tasks/{id}", {}).get("hits"):
            fails.append("a route no test requests is the whole point — it must be reported")
        # REJECT-NOTHING PIN, twice: a plainly requested route, and one requested only
        # through http.MethodGet. The constant form is most of the corpus, and a tool that
        # misses it reports covered routes as holes and is worse than no tool.
        if not rows.get("GET /tasks", {}).get("hits"):
            fails.append("GET /tasks IS requested — reporting it makes every row noise")
        if not rows.get("GET /health", {}).get("hits"):
            fails.append("http.MethodGet is a request too; missing it invents holes")
        if audit_tree(tree / "nope") != []:
            fails.append("a tree with no routes must report nothing, not crash")

    # THE THREE SHAPES THAT EACH COST A DRAFT. Every one of them was first reported as a
    # hole against a suite that plainly exercises the route.
    with tempfile.TemporaryDirectory() as d:
        tree = pathlib.Path(d)
        (tree / "router.go").write_text(
            'package main\n'
            'func R() {\n'
            '\tmux.HandleFunc("PUT /kv/{key}", put)\n'
            '\tmux.HandleFunc("GET /kv/{key}", get)\n'
            '\tmux.HandleFunc("GET /ping", ping)\n'
            '}\n')
        (tree / "main_test.go").write_text(
            'package main\n'
            'func TestY(t *testing.T) {\n'
            # path concatenated onto a base URL, method as a constant
            '\treq, _ := http.NewRequest(http.MethodPut, srv.URL+"/kv/a", nil)\n'
            # method is the FUNCTION NAME, path concatenated with spaces around +
            '\tres, _ := http.Get(srv.URL + "/kv/missing")\n'
            # no method anywhere: a helper that fixes GET internally
            '\trec := hit(mux, "/ping", "clientA")\n'
            '}\n')
        rows = {r["route"]: r for r in audit_tree(tree)}
        if not rows.get("PUT /kv/{key}", {}).get("hits"):
            fails.append("srv.URL+\"/kv/a\" is a request to /kv/{key} — concatenation is "
                         "not a reason to call a route cold")
        if not rows.get("GET /kv/{key}", {}).get("hits"):
            fails.append("http.Get names its own method; missing it invents a hole")
        ping = rows.get("GET /ping", {})
        if ping.get("hits"):
            fails.append("no method literal reaches /ping — claiming an attributed GET here "
                         "would let a GET-only helper certify a DELETE elsewhere")
        if not ping.get("path_seen"):
            fails.append("the /ping path IS named by a test — 'never requested' is a claim "
                         "about the door, and this door was named")

    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — flags the door nobody opens, silent on the ones tests use"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    trees = [pathlib.Path(a) for a in sys.argv[1:] if not a.startswith("-")]
    if not trees:
        trees = sorted(pathlib.Path("generated").glob("*-v4"))
    total = flagged = 0
    for tree in trees:
        rows = audit_tree(tree)
        if not rows:
            continue
        # COLD means the PATH never appears at all. A route whose path is named but whose
        # method could not be attributed is reported separately and NOT counted here: the
        # number has to mean "no test opens this door", not "my regexes lost the method".
        cold = [r for r in rows if not r["hits"] and not r["path_seen"]]
        total += len(rows)
        flagged += len(cold)
        print(f"\n{tree.name:<18} {len(rows)} routes, {len(cold)} never requested")
        for r in rows:
            if r["hits"]:
                mark = f"{r['hits']}x"
            elif r["path_seen"]:
                mark = "path seen"
            else:
                mark = "NEVER REQUESTED"
            print(f"   {mark:<16} {r['route']}")
    print(f"\n{flagged} route(s) no test requests, out of {total} registered "
          f"in {len(trees)} tree(s)")
    if not total:
        print("no routes found — this audit had nothing to check, which is not a pass")
    print("A hit is a CANDIDATE. A health endpoint nobody asserts is a judgement call; a\n"
          "resource route nobody opens is every promise on it undefended at once.")
