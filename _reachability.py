#!/usr/bin/env python3
"""Which mutation sites sit on lines the test suite NEVER EXECUTES?

WHY. Three separate times this corpus has produced a SURVIVED row that was not a hole
because the line does not run: the seventeen dead `else { 500 }` branches (largest non-hole
category in the capstone), expreval's consumeOperator bound, tasks-api's subsumed Title
guard. Each was settled by a coverage run or a code-read, PER ROW.

That was affordable at 48 candidates. The walk fix is about to make the sweep substantially
larger — workapi alone goes from 6 rows to 36 — and per-row reading does not scale. But the
question does not need a probe at all. `go test -coverprofile` already knows which lines ran,
and it costs ONE test run for the whole artifact instead of one per row.

    A mutation on a line no test executes cannot be caught by any assertion whatsoever.
    That is a fact about REACHABILITY, and it is knowable before the mutation is applied.

So this front-runs the sweep: sites on never-executed lines are answered in advance, and the
expensive per-row probing is spent on rows that could actually move.

WHAT IT IS NOT. Coverage is the TEST suite's reach, not the program's. A line no test runs
may still be reachable in production — that is precisely the difference between "no test
defends this" and "nothing can reach this", and only the second makes a row a non-hole. The
capstone settled the 500-else class on BOTH: never executed AND unreachable through the
shipped composition, because the concrete in-memory store returns only the sentinels the
`if` already handles. This tool gives the first half cheaply and says so.

    python _reachability.py generated/workapi-v4
    python _reachability.py --self-test
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _hole_hunt import CODE, SWAP, BOUND, BOUND_LINE, WRAP, HEADER, go_files


def coverage(art: pathlib.Path) -> dict[str, dict[int, int]] | None:
    """{relative file -> {line -> times executed}}, or None if the suite will not run."""
    mod = next((p for p in art.rglob("go.mod")), None)
    if mod is None:
        return None
    root = mod.parent
    module = ""
    for ln in mod.read_text().splitlines():
        if ln.startswith("module "):
            module = ln.split(None, 1)[1].strip()
            break
    with tempfile.NamedTemporaryFile(suffix=".cover", delete=False) as tf:
        out = tf.name
    r = subprocess.run(["go", "test", "-coverprofile", out, "./..."],
                       cwd=root, capture_output=True, text=True)
    text = pathlib.Path(out).read_text(errors="replace") if pathlib.Path(out).exists() else ""
    if not text.strip():
        return None
    if r.returncode != 0 and "no test files" not in r.stdout:
        # A RED suite still produces a profile, and its zeroes mean "the test failed before
        # reaching this", not "unreachable". Refusing is the only honest answer.
        return None
    hits: dict[str, dict[int, int]] = {}
    for ln in text.splitlines()[1:]:
        try:
            loc, _nstmt, count = ln.rsplit(" ", 2)
            f, rng = loc.split(":", 1)
            a, b = rng.split(",")
            start, end, n = int(a.split(".")[0]), int(b.split(".")[0]), int(count)
        except ValueError:
            continue
        rel = f[len(module) + 1:] if module and f.startswith(module + "/") else f
        d = hits.setdefault(rel, {})
        for L in range(start, end + 1):
            d[L] = max(d.get(L, 0), n)
    return hits


def sites(art: pathlib.Path) -> list[tuple[str, int, str, str]]:
    """(relative file, 1-based line, shape, source) for every line a shape would mutate."""
    out = []
    for f in go_files(art):
        rel = str(f.relative_to(art))
        for i, ln in enumerate(f.read_text(errors="ignore").splitlines()):
            if ln.strip().startswith("//"):
                continue
            m = CODE.match(ln)
            if m and m.group(1) in SWAP:
                out.append((rel, i + 1, "status", ln.strip()))
            if HEADER.match(ln):
                out.append((rel, i + 1, "header", ln.strip()))
            if BOUND_LINE.search(ln) and BOUND.search(ln):
                out.append((rel, i + 1, "boundary", ln.strip()))
            if WRAP.search(ln):
                out.append((rel, i + 1, "wrap", ln.strip()))
    return out


def audit(art: pathlib.Path) -> tuple[list[dict] | None, str]:
    cov = coverage(art)
    if cov is None:
        return None, ("no usable coverage profile — a RED or unbuildable suite produces "
                      "zeroes that mean 'the test stopped earlier', not 'unreachable'")
    rows = []
    for rel, line, shape, src in sites(art):
        runs = cov.get(rel, {}).get(line)
        rows.append({"file": rel, "line": line, "shape": shape, "src": src,
                     "runs": runs, "cold": runs == 0})
    return rows, ""


def self_test() -> int:
    fails = []
    with tempfile.TemporaryDirectory() as d:
        art = pathlib.Path(d)
        (art / "go.mod").write_text("module example.com/t\n\ngo 1.23\n")
        # Hit() is exercised; Cold() is registered nowhere a test reaches.
        (art / "t.go").write_text(
            'package t\n\n'
            'import "net/http"\n\n'
            'func Hit(w http.ResponseWriter) {\n'
            '\thttp.Error(w, "x", http.StatusBadRequest)\n'
            '}\n\n'
            'func Cold(w http.ResponseWriter) {\n'
            '\thttp.Error(w, "y", http.StatusInternalServerError)\n'
            '}\n')
        (art / "t_test.go").write_text(
            'package t\n\n'
            'import (\n\t"net/http/httptest"\n\t"testing"\n)\n\n'
            'func TestHit(t *testing.T) { Hit(httptest.NewRecorder()) }\n')
        rows, note = audit(art)
        if rows is None:
            fails.append(f"a green artifact must produce a profile: {note}")
        else:
            by_line = {r["line"]: r for r in rows}
            hot = [r for r in rows if "StatusBadRequest" in r["src"]]
            cold = [r for r in rows if "StatusInternalServerError" in r["src"]]
            if not hot or hot[0]["cold"]:
                fails.append(f"the line a test executes must NOT be reported cold: {hot}")
            if not cold or not cold[0]["cold"]:
                fails.append(f"the line no test reaches is the whole point: {cold}")
            if len(rows) != 2:
                fails.append(f"both status sites must be found, and only those: "
                             f"{[(r['line'], r['shape']) for r in rows]}")
            del by_line

    # A RED suite must REFUSE, not report every line cold — that failure direction would
    # mark a whole artifact unreachable and retire real holes without asking.
    with tempfile.TemporaryDirectory() as d:
        art = pathlib.Path(d)
        (art / "go.mod").write_text("module example.com/t\n\ngo 1.23\n")
        (art / "t.go").write_text('package t\n\nimport "net/http"\n\n'
                                  'func Hit(w http.ResponseWriter) {\n'
                                  '\thttp.Error(w, "x", http.StatusBadRequest)\n}\n')
        (art / "t_test.go").write_text('package t\n\nimport "testing"\n\n'
                                       'func TestRed(t *testing.T) { t.Fatal("red") }\n')
        rows, note = audit(art)
        if rows is not None:
            fails.append("a RED suite must refuse: its zeroes mean the test stopped, not "
                         "that the line is unreachable")

    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else
                           "ok — cold lines named, executed lines spared, red suites refused"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    targets = [pathlib.Path(a) for a in sys.argv[1:] if not a.startswith("-")]
    if not targets:
        targets = sorted(pathlib.Path("generated").glob("*-v4"))
    total = cold_n = 0
    for art in targets:
        rows, note = audit(art)
        if rows is None:
            print(f"\n{art.name}: NOT MEASURED — {note}")
            continue
        cold = [r for r in rows if r["cold"]]
        unknown = [r for r in rows if r["runs"] is None]
        total += len(rows)
        cold_n += len(cold)
        print(f"\n{art.name}  {len(rows)} mutation site(s), {len(cold)} on lines NEVER "
              f"EXECUTED, {len(unknown)} with no coverage block")
        for r in cold:
            print(f"   COLD  {r['file']}:{r['line']:<4} {r['shape']:<9} {r['src'][:58]}")
    print(f"\n{cold_n} site(s) on never-executed lines, out of {total} in "
          f"{len(targets)} artifact(s)")
    print("COLD answers ONE half of 'is this a hole': no assertion can catch a mutation on a\n"
          "line no test runs. The other half — whether the shipped composition can reach it\n"
          "at all — still needs a read. Coverage is the SUITE's reach, not the program's.")
