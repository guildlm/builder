#!/usr/bin/env python3
"""A SURVIVED boundary flip is not yet a hole: ask whether any test COULD have seen it.

_hole_hunt's sixth shape flips one comparison and reports SURVIVED when the suite stays
green. That reads as "undefended", but a boundary flip has a second way to stay green:
NO INPUT DISTINGUISHES THE TWO PROGRAMS. `_hole_hunt` filters two such shapes
syntactically (a clamp that assigns the value it just compared, `if x < 0 { return -x }`),
and syntax is the wrong instrument for the question — inertness is semantic:

    if offset >= len(items) { return []T{} }        // flipped to >
    ...
    if limit <= 0 || limit > len(items)-offset { limit = len(items) - offset }
    return items[offset : offset+limit]

At offset == len(items) the flipped version falls through, computes limit = 0, and
returns items[n:n] — an empty slice, exactly like the branch it skipped. Measured over
every (items, limit, offset) combination in the corpus's range, the ONLY distinguishable
case is a nil input (`[]` vs `null` once marshalled), and all three stores build their
slices with make(), so nil never arrives. Three of the fifteen boundary survivors are
that shape: green because nothing was broken, not because nothing was watching.

So this tool asks the question the other way round. For each survivor I write the probe
test I would put in the spec, and require it to:

    PASS on the unmutated artifact   (or the probe is wrong, not the artifact)
    FAIL on the mutant               (or no test of that behaviour could ever catch it)

and it must be the PROBE that fails, not the artifact's own suite — a mutation the suite
already catches was never a survivor and the row that said so is stale.

    python _bound_probe.py              # every registered probe
    python _bound_probe.py taskflow     # one artifact
    python _bound_probe.py --self-test  # planted fixtures: observable, inert, broken probe

VERDICTS
  OBSERVABLE        the probe distinguishes -> a REAL hole, and this is the test that
                    closes it. The probe body is the assertion to put in the spec.
  INERT-OR-WEAK     probe passes on both. Either the flip changes nothing observable, or
                    my probe is too weak. Never reported as "inert" on its own: absence
                    of a distinguishing test is not proof that none exists.
  PROBE-RED         the probe fails on the UNMUTATED artifact — it asserts behaviour the
                    artifact does not have. My bug, reported as mine.
  DEFENDED-ALREADY  the mutant went red but the probe passed: the artifact's own suite
                    catches this. The SURVIVED row that sent me here is out of date.
"""
import pathlib
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, "/Users/fatihturker/Desktop/Personal/Dev/guildlm/builder")
from _hole_hunt import BOUND, BOUND_FLIP, BOUND_LINE, inert_flip, replace_at
from _teeth_suite import verdict_for, GEN


NIL_SLICE = re.compile(r"(\w+) := make\((\[\][\w.]+), 0(?:, [^()]*(?:\([^()]*\))?[^()]*)?\)")


def nil_slice(occurrence: int = 0):
    """`out := make([]T, 0, n)` -> `var out []T`: the accumulator starts NIL.

    Every observable behaviour is identical — append, len, range, indexing — except one:
    an EMPTY result marshals as `null` instead of `[]`. A client that iterates the
    response breaks on null; a Go test that round-trips through the same struct cannot
    see it, and neither can any assertion on len() or on the decoded value.

    This is the sibling of the json-tag shape. Both are invisible to a round-trip and
    visible only to an assertion on the RAW body, which is why the corpus keeps growing
    tests that cannot see either.
    """
    def mut(text: str):
        seen = 0
        for m in NIL_SLICE.finditer(text):
            if seen != occurrence:
                seen += 1
                continue
            return text[:m.start()] + f"var {m.group(1)} {m.group(2)}" + text[m.end():]
        return None
    return mut


def flip_site(needle: str, occurrence: int = 0):
    """Flip the boundary operator on the line holding `needle`, by INDEX not by text.

    Same lesson as _hole_hunt.replace_at: `if offset >= len(items)` appears twice in
    taskapipro's service.go, and a text-matching mutator either refuses both or silently
    edits the wrong one. The occurrence selector is what makes a per-site verdict possible
    at all — the corpus rows already conflate two config guards under one identical tag.
    """
    def mut(text: str):
        seen = 0
        for i, ln in enumerate(text.splitlines()):
            if needle not in ln:
                continue
            if seen != occurrence:
                seen += 1
                continue
            m = BOUND.search(ln)
            if not m:
                return None
            flipped = ln.replace(m.group(1), BOUND_FLIP[m.group(1)], 1)
            return replace_at(i, ln, flipped)(text)
        return None
    return mut


# ---------------------------------------------------------------------------
# The probes. Each is the test I would ask the spec for, written once and reused
# across the artifacts that share the shape — five of the twenty-five specs describe
# the SAME Chain contract, in the same words, and grew the same undefended loop.
# ---------------------------------------------------------------------------

def chain_probe(pkg: str) -> str:
    """Chain(h, A, B) must run A outermost, then B, then h — and must apply BOTH.

    `for i := len(mws)-1; i >= 0; i--` flipped to `i > 0` never applies mws[0], so the
    FIRST-listed middleware — the outermost, which in every one of these artifacts is
    Logging or Recover — silently disappears. Recording the call order in a slice is
    what makes the flip visible: asserting only the response would pass, because the
    handler still runs and still writes 200.
    """
    return f'''package {pkg}

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestChainAppliesEveryMiddlewareOutermostFirst(probe *testing.T) {{
	order := []string{{}}
	mark := func(name string) Middleware {{
		return func(next http.Handler) http.Handler {{
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {{
				order = append(order, name)
				next.ServeHTTP(w, r)
			}})
		}}
	}}
	inner := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {{
		order = append(order, "handler")
	}})
	Chain(inner, mark("first"), mark("second")).ServeHTTP(
		httptest.NewRecorder(), httptest.NewRequest("GET", "/", nil))
	if got := strings.Join(order, ","); got != "first,second,handler" {{
		probe.Fatalf("Chain order = %q, want %q", got, "first,second,handler")
	}}
}}
'''


def config_probe(pkg: str, field: str, others: str, want: str) -> str:
    """Validate must REJECT a zero `field`. `<= 0` flipped to `< 0` accepts it."""
    return f'''package {pkg}

import "testing"

func TestValidateRejectsZero{field}(probe *testing.T) {{
	cfg := Config{{{others}{field}: 0}}
	if err := cfg.Validate(); err == nil {{
		probe.Fatalf("Validate() with {field}=0 = nil, want an error ({want})")
	}}
}}
'''


def paginate_probe(pkg: str, call: str) -> str:
    """offset == len(items) must yield an empty page — the flip's only candidate input."""
    return f'''package {pkg}

import "testing"

func TestPaginateAtOffsetEqualToLength(probe *testing.T) {{
	items := []int{{1, 2, 3}}
	got := {call}
	if len(got) != 0 {{
		probe.Fatalf("paginate(3 items, offset=3) returned %d items, want 0", len(got))
	}}
	if got == nil {{
		probe.Fatalf("paginate returned a nil slice; an empty page must marshal as [], not null")
	}}
}}
'''


BITSET_PROBE = '''package bitset

import "testing"

func TestClearOutOfRangeIndexIsANoOp(probe *testing.T) {
	b := New()
	b.Set(0)
	b.Clear(64)
	if !b.Test(0) {
		probe.Fatalf("Clear(64) on a one-word set disturbed bit 0")
	}
}

func TestTestOutOfRangeIndexIsFalse(probe *testing.T) {
	b := New()
	b.Set(0)
	if b.Test(64) {
		probe.Fatalf("Test(64) on a one-word set = true, want false")
	}
}
'''

# 64 is the FIRST index of the next word, i.e. wordIndex == len(words) exactly — the one
# input the flip moves. 63 stays inside word 0 and 128 is two words past the end, and
# neither tells the two programs apart: the untested case is always the boundary itself.

EXPREVAL_PROBE = '''package eval

import "testing"

func TestOperatorPositionAtEndOfInput(probe *testing.T) {
	for _, expr := range []string{"1+", "1*", "1 + ", "(1+2", "1+2*"} {
		if _, err := Eval(expr); err == nil {
			probe.Fatalf("Eval(%q) = nil error, want an error", expr)
		}
	}
}
'''

LEDGER_PROBE = '''package money

import "testing"

func TestParseRejectsALeadingDecimalPoint(probe *testing.T) {
	if _, err := Parse(".50"); err == nil {
		probe.Fatalf("Parse(\\".50\\") = nil error, want an error")
	}
}
'''

PROBES = [
    # (label, artifact, rel file to mutate, needle, occurrence, probe path, probe source)
    ("taskflow  Chain", "taskflow-v4", "middleware.go", "for i := len(mws) - 1", 0,
     "zz_probe_test.go", chain_probe("main")),
    ("usersapi  Chain", "usersapi-v4", "middleware.go", "for i := len(mws) - 1", 0,
     "zz_probe_test.go", chain_probe("main")),
    ("taskapi   Chain", "taskapi-v4", "internal/api/middleware.go", "for i := len(mws) - 1", 0,
     "internal/api/zz_probe_test.go", chain_probe("api")),
    ("taskapipro Chain", "taskapipro-v4", "internal/api/middleware.go", "for i := len(mws) - 1", 0,
     "internal/api/zz_probe_test.go", chain_probe("api")),
    ("workapi   Chain", "workapi-v4", "internal/api/middleware.go", "for i := len(mws) - 1", 0,
     "internal/api/zz_probe_test.go", chain_probe("api")),

    ("workapi   QueueSize<=0", "workapi-v4", "internal/config/config.go", "c.QueueSize <= 0", 0,
     "internal/config/zz_probe_test.go",
     config_probe("config", "QueueSize", 'Addr: ":8080", AuthToken: "tok", ', "queue size must be positive")),
    ("taskapipro DefaultPageSize<=0", "taskapipro-v4", "internal/config/config.go",
     "c.DefaultPageSize <= 0", 0, "internal/config/zz_probe_test.go",
     config_probe("config", "DefaultPageSize", 'Addr: ":8080", MaxPageSize: 100, ',
                  "default page size must be positive")),
    ("taskapipro MaxPageSize<=0", "taskapipro-v4", "internal/config/config.go",
     "c.MaxPageSize <= 0", 0, "internal/config/zz_probe_test.go",
     config_probe("config", "MaxPageSize", 'Addr: ":8080", DefaultPageSize: 20, ',
                  "max page size must be positive")),

    ("taskflow  paginate", "taskflow-v4", "pagination.go", "if offset >= len(items)", 0,
     "zz_probe_test.go", paginate_probe("main", "paginate(items, 10, 3)")),
    ("taskapipro paginate", "taskapipro-v4", "internal/service/service.go",
     "if offset >= len(items)", 0, "internal/service/zz_probe_test.go",
     paginate_probe("service", "paginate(items, 10, 3)")),
    ("workapi   paginate", "workapi-v4", "internal/service/service.go",
     "if offset >= len(items)", 0, "internal/service/zz_probe_test.go",
     paginate_probe("service", "paginate(items, 10, 3)")),

    ("bitset    Clear<len", "bitset-v4", "bitset.go", "if wordIndex < len(b.words)", 0,
     "zz_probe_test.go", BITSET_PROBE),
    ("bitset    Test>=len", "bitset-v4", "bitset.go", "if wordIndex >= len(b.words)", 1,
     "zz_probe_test.go", BITSET_PROBE),
    ("expreval  consumeOperator", "expreval-v4", "eval.go", "if p.pos >= len(p.input) {", 0,
     "zz_probe_test.go", EXPREVAL_PROBE),
    ("ledger    dot<0", "ledger-v4", "internal/money/money.go", "if dot < 0", 0,
     "internal/money/zz_probe_test.go", LEDGER_PROBE),

    # NOT a boundary flip, and here because the boundary work turned it up: paginate is
    # inert ONLY because every store builds its slice with make(), and nothing in any spec
    # or any test requires that. The day the accumulator is declared `var out []Task`
    # instead, an empty list goes out as `null` and every client that iterates it breaks.
    ("taskflow  empty list []", "taskflow-v4", "store.go", nil_slice(0),
     0, "zz_probe_test.go", '''package main

import (
	"net/http/httptest"
	"strings"
	"testing"
)

func TestEmptyListMarshalsAsAnEmptyArray(probe *testing.T) {
	rec := httptest.NewRecorder()
	NewRouter(NewStore()).ServeHTTP(rec, httptest.NewRequest("GET", "/tasks", nil))
	if got := strings.TrimSpace(rec.Body.String()); got != "[]" {
		probe.Fatalf("GET /tasks on an empty store = %q, want []", got)
	}
}
'''),
    # The same mutation on three artifacts that have NO paginate between the store and the
    # encoder. taskflow above is the control: identical mutation, INERT, because paginate's
    # `return []T{}` normalises the nil away. These three ship `null`.
    ("usersapi  empty list []", "usersapi-v4", "store.go", nil_slice(0), 0,
     "zz_probe_test.go", '''package main

import (
	"net/http/httptest"
	"strings"
	"testing"
)

func TestEmptyListMarshalsAsAnEmptyArray(probe *testing.T) {
	rec := httptest.NewRecorder()
	NewRouter(NewMemStore()).ServeHTTP(rec, httptest.NewRequest("GET", "/users", nil))
	if got := strings.TrimSpace(rec.Body.String()); got != "[]" {
		probe.Fatalf("GET /users on an empty store = %q, want []", got)
	}
}
'''),
    ("tasks-api empty list []", "tasks-api-v4", "store.go", nil_slice(0), 0,
     "zz_probe_test.go", '''package main

import (
	"net/http/httptest"
	"strings"
	"testing"
)

func TestEmptyListMarshalsAsAnEmptyArray(probe *testing.T) {
	rec := httptest.NewRecorder()
	NewRouter(NewAPI(NewMemStore())).ServeHTTP(rec, httptest.NewRequest("GET", "/tasks", nil))
	if got := strings.TrimSpace(rec.Body.String()); got != "[]" {
		probe.Fatalf("GET /tasks on an empty store = %q, want []", got)
	}
}
'''),
    ("taskapi   empty list []", "taskapi-v4", "internal/store/memory.go", nil_slice(0), 0,
     "internal/api/zz_probe_test.go", '''package api

import (
	"io"
	"log/slog"
	"net/http/httptest"
	"strings"
	"testing"

	"guildlm.dev/taskapi/internal/store"
)

func TestEmptyListMarshalsAsAnEmptyArray(probe *testing.T) {
	rec := httptest.NewRecorder()
	NewRouter(store.NewMemStore(), slog.New(slog.NewTextHandler(io.Discard, nil))).
		ServeHTTP(rec, httptest.NewRequest("GET", "/tasks", nil))
	if got := strings.TrimSpace(rec.Body.String()); got != "[]" {
		probe.Fatalf("GET /tasks on an empty store = %q, want []", got)
	}
}
'''),
]


def judge(art: pathlib.Path, rel: str, needle: str, occ: int,
          probe_path: str, probe_src: str) -> tuple[str, str]:
    """Two runs through the SAME verdict machinery, so the baseline-green rule is shared.

    Pass 1 has no mutation and exists only to confirm the probe compiles and passes on the
    artifact as generated. Pass 2 mutates with the probe present.
    """
    # `needle` may be a ready-made mutator instead of a line to find, so a family whose
    # mutation is not an operator flip rides the same machinery.
    mutator = needle if callable(needle) else flip_site(needle, occ)
    clean, note = verdict_for(art, rel, lambda t: t, extra={probe_path: probe_src})
    if clean in ("SKIP", "NOTESTS", "NOAPPLY"):
        return clean, note
    if clean == "BASELINE-RED":
        return "PROBE-RED", "the probe fails on the unmutated artifact — fix the probe: " + note
    v, note = verdict_for(art, rel, mutator, extra={probe_path: probe_src})
    if v in ("SKIP", "NOAPPLY", "NOTESTS", "BASELINE-RED"):
        return v, note
    if v == "SURVIVED":
        return "INERT-OR-WEAK", "probe passes on both — no input this probe tries tells them apart"
    if any(name in note for name in
           ("TestChain", "TestValidateRejectsZero", "TestPaginate", "TestClearOutOfRange",
            "TestTestOutOfRange", "TestOperatorPosition", "TestParseRejects",
            "TestEmptyListMarshals")):
        return "OBSERVABLE", note
    return "DEFENDED-ALREADY", note + " — the artifact's own suite sees this; the SURVIVED row is stale"


_MOD = "module example.com/t\n\ngo 1.23\n"
# An OBSERVABLE flip: >= 10 vs > 10 differ at exactly one input, and the probe tries it.
_OBS = "package t\n\nfunc AtLeastTen(n int) bool {\n\treturn n >= 10\n}\n"
_OBS_PROBE = ('package t\n\nimport "testing"\n\nfunc TestChainBoundary(probe *testing.T) {\n'
              '\tif !AtLeastTen(10) {\n\t\tprobe.Fatalf("AtLeastTen(10) = false, want true")\n\t}\n}\n')
# A GENUINELY INERT flip: negating zero yields zero, so `< 0` and `<= 0` agree everywhere.
_INERT = "package t\n\nfunc Abs(n int) int {\n\tif n < 0 {\n\t\treturn -n\n\t}\n\treturn n\n}\n"
_INERT_PROBE = ('package t\n\nimport "testing"\n\nfunc TestChainBoundary(probe *testing.T) {\n'
                '\tif Abs(0) != 0 {\n\t\tprobe.Fatalf("Abs(0) = %d, want 0", Abs(0))\n\t}\n}\n')
# A BROKEN probe: asserts the opposite of what the unmutated artifact does.
_BAD_PROBE = ('package t\n\nimport "testing"\n\nfunc TestChainBoundary(probe *testing.T) {\n'
              '\tif AtLeastTen(10) {\n\t\tprobe.Fatalf("AtLeastTen(10) = true, want false")\n\t}\n}\n')
# The artifact's OWN suite already catches it -> the survivor row was stale.
_OWN_SUITE = ('package t\n\nimport "testing"\n\nfunc TestOwn(t *testing.T) {\n'
              '\tif !AtLeastTen(10) {\n\t\tt.Fatalf("AtLeastTen(10) = false, want true")\n\t}\n}\n')
_WEAK_PROBE = ('package t\n\nimport "testing"\n\nfunc TestChainBoundary(probe *testing.T) {\n'
               '\tif !AtLeastTen(11) {\n\t\tprobe.Fatalf("AtLeastTen(11) = false, want true")\n\t}\n}\n')


def self_test() -> int:
    """Four planted answers. Without these the tool can only ever agree with me.

    The fourth is the one worth having: a probe that passes on both because it never
    tries the boundary looks EXACTLY like a genuinely inert flip, and INERT-OR-WEAK is
    named the way it is so that a report can never quietly upgrade the second to the first.
    """
    cases = [
        ("OBSERVABLE", _OBS, _OBS_PROBE, "n >= 10", "t_test.go",
         'package t\n\nimport "testing"\n\nfunc TestOther(t *testing.T) {\n\t_ = AtLeastTen(3)\n}\n'),
        ("INERT-OR-WEAK", _INERT, _INERT_PROBE, "if n < 0", "t_test.go",
         'package t\n\nimport "testing"\n\nfunc TestOther(t *testing.T) {\n\t_ = Abs(3)\n}\n'),
        ("PROBE-RED", _OBS, _BAD_PROBE, "n >= 10", "t_test.go",
         'package t\n\nimport "testing"\n\nfunc TestOther(t *testing.T) {\n\t_ = AtLeastTen(3)\n}\n'),
        ("DEFENDED-ALREADY", _OBS, _WEAK_PROBE, "n >= 10", "t_test.go", _OWN_SUITE),
    ]
    failures = []
    for want, impl, probe, needle, suite_name, suite in cases:
        with tempfile.TemporaryDirectory() as td:
            art = pathlib.Path(td) / "art"
            art.mkdir()
            (art / "go.mod").write_text(_MOD)
            (art / "t.go").write_text(impl)
            (art / suite_name).write_text(suite)
            got, note = judge(art, "t.go", needle, 0, "zz_probe_test.go", probe)
        if got != want:
            failures.append(f"expected {want}, got {got} ({note})")
    # DEFENDED-ALREADY must not be reachable by a probe that DOES see the flip: the
    # discriminator is which test went red, and a run where both fail is an OBSERVABLE.
    with tempfile.TemporaryDirectory() as td:
        art = pathlib.Path(td) / "art"
        art.mkdir()
        (art / "go.mod").write_text(_MOD)
        (art / "t.go").write_text(_OBS)
        (art / "t_test.go").write_text(_OWN_SUITE)
        got, _ = judge(art, "t.go", "n >= 10", 0, "zz_probe_test.go", _OBS_PROBE)
        if got != "OBSERVABLE":
            failures.append(f"probe+suite both red must be OBSERVABLE, got {got}")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("OK — a distinguishable flip is OBSERVABLE, an indistinguishable one is "
          "INERT-OR-WEAK,\n     a probe that contradicts the artifact is PROBE-RED, and a "
          "flip the suite already\n     catches is DEFENDED-ALREADY rather than a fresh hole")
    return 0


def locate(art: pathlib.Path, rel: str) -> int:
    """Which OCCURRENCE in this file is the survivor? Flip each one alone and report.

    logs/hole-hunt-rows.tsv addresses a site by (artifact, file, tag), and the tag is the
    operator pair — so expreval's eval.go carries five rows reading `boundary >= -> >`,
    four CAUGHT and one SURVIVED, with nothing to say WHICH of the five parser bounds is
    undefended. taskapipro's config.go carries the same ambiguity across two guards that
    turn out to have opposite answers: one observable, one masked downstream.

    A tag is not an address. This prints the line number and the source line beside each
    verdict, which is the address, and it is the same per-site lesson the mutation registry
    had to learn when a multi-site sort mutation reported its STRONGEST site.
    """
    src = art / rel
    if not src.exists():
        raise SystemExit(f"{src} does not exist")
    lines = src.read_text(errors="ignore").splitlines()
    sites = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("//") or not BOUND_LINE.search(ln) or not BOUND.search(ln):
            continue
        sites.append((i, ln))
    if not sites:
        raise SystemExit(f"no boundary site in {rel} — nothing was measured, which is "
                         f"not the same as no holes")
    print(f"{art.name}/{rel}: {len(sites)} boundary site(s)\n")
    for occ, (i, ln) in enumerate(sites):
        op = BOUND.search(ln).group(1)
        body = lines[i + 1] if i + 1 < len(lines) else ""
        if inert_flip(ln, body):
            print(f"  line {i+1:<4} occ {occ}  {op} -> {BOUND_FLIP[op]:<3} INERT      {ln.strip()}")
            continue
        v, _ = verdict_for(art, rel, flip_site(ln.strip(), 0)
                           if lines.count(ln) == 1 else _flip_index(i, ln))
        print(f"  line {i+1:<4} occ {occ}  {op} -> {BOUND_FLIP[op]:<3} {v:<10} {ln.strip()}",
              flush=True)
    return 0


def _flip_index(idx: int, line: str):
    """Flip by LINE INDEX, for files where the same source line appears more than once."""
    op = BOUND.search(line).group(1)
    return replace_at(idx, line, line.replace(op, BOUND_FLIP[op], 1))


def main() -> int:
    if "--locate" in sys.argv:
        rest = [a for a in sys.argv[1:] if not a.startswith("-")]
        if len(rest) != 2:
            raise SystemExit("usage: _bound_probe.py --locate <artifact-dir> <file.go>")
        return locate(pathlib.Path(rest[0]), rest[1])
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    rows = [p for p in PROBES if not wanted or any(w in p[0] or w in p[1] for w in wanted)]
    if wanted and not rows:
        raise SystemExit("no probe matched " + " ".join(wanted) +
                         "\nknown: " + ", ".join(sorted({p[1] for p in PROBES})))
    print(f"{'probe':<28} {'verdict':<17} note")
    print("-" * 100)
    out = []
    for label, art, rel, needle, occ, ppath, psrc in rows:
        v, note = judge(GEN / art, rel, needle, occ, ppath, psrc)
        out.append((label, v))
        print(f"{label:<28} {v:<17} {note}", flush=True)

    # WRITE THE ROWS, but only for a FULL run. logs/hole-hunt-rows.tsv stays exactly what
    # the sweep produced — raw verdicts are worth more unedited — so the interpretation
    # lives beside it under the same (artifact, file) key rather than on top of it. A
    # partial run would drop every probe it did not select, so a selected run prints and
    # writes nothing.
    if not wanted:
        rows = "\n".join(f"{a}\t{rel}\t{label.split(None, 1)[1]}\t{v}"
                         for (label, a, rel, *_), (_, v) in zip(PROBES, out))
        pathlib.Path("logs/bound-probe-rows.tsv").write_text(rows + "\n")
        print("wrote logs/bound-probe-rows.tsv\n")

    print()
    obs = [l for l, v in out if v == "OBSERVABLE"]
    inert = [l for l, v in out if v == "INERT-OR-WEAK"]
    print(f"{len(obs)} OBSERVABLE (real holes, probe body is the closure):")
    for l in obs:
        print("   ", l)
    print(f"{len(inert)} INERT-OR-WEAK (green for a reason that is not the tests):")
    for l in inert:
        print("   ", l)
    if not out:
        raise SystemExit("NOTHING WAS PROBED — that is not 'no holes'.")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    # NEVER PROBE A MOVING TREE. Same rule as _hole_hunt, and it applies harder here: a
    # half-written artifact has no _test.go, so the probe passes on the baseline, passes on
    # the mutant, and the verdict reads INERT-OR-WEAK — "nothing was broken" — about a tree
    # that was simply not finished. The reassuring answer is the wrong one, again.
    from _corpus_state import check as _corpus_check
    _selected = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--locate" in sys.argv:
        if _selected and _corpus_check(_selected[0]) == "refuse":
            raise SystemExit(2)
    elif _selected:
        if any(_corpus_check(GEN / p[1]) == "refuse" for p in PROBES
               if any(w in p[0] or w in p[1] for w in _selected)):
            raise SystemExit(2)
    elif any(_corpus_check(GEN / p[1]) == "refuse" for p in PROBES):
        raise SystemExit(2)
    raise SystemExit(main())
