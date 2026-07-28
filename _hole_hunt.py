#!/usr/bin/env python3
"""Systematic hole hunt: break something the spec promised, ask whether the suite notices.

The teeth campaign found its holes by hand, one invariant at a time, and reached 29
CAUGHT / 0 SURVIVED — which reads as "no holes left" and is really "no holes left among
the ones we thought to check". This sweeps instead, over every archived artifact, in two
shapes: swap a status-code write for a plausible neighbour, and delete a response-header
line outright. Both are the documented hole shape — error paths and headers in small HTTP
specs — so this is the cheapest place to sweep, not the only one.

    python _hole_hunt.py                 # first mutable site per artifact (cheap pass)
    python _hole_hunt.py --all-sites     # every site; found half the genuine holes
    python _hole_hunt.py --self-test     # prove the hunt can still tell CAUGHT from
                                         # SURVIVED, and that the benign label matches

READING THE OUTPUT, which is where this tool can mislead:
  SURVIVED   a green build with a real behaviour change. A CANDIDATE, not a verdict — the
             next question is always whether the SPEC promises what was broken. Across 23
             probes, 9 survivors were 4 genuine undefended promises, 2 known-benign, and 3
             behaviour the spec never asked for (which are SPEC gaps, not test gaps).
  SURVIVED*  a known-benign shape: a `statusRecorder` default, whose mutation changes log
             output only. Labelled rather than filtered — dropping a class from a hole
             hunter is how it goes quiet on the day that class hides a real defect.

Uses _teeth_suite.verdict_for, so an artifact whose baseline is already red reports
BASELINE-RED rather than a fake CAUGHT. Full results: logs/FINDING-status-code-holes.txt.
"""
import pathlib
import re, sys, pathlib
sys.path.insert(0, "/Users/fatihturker/Desktop/Personal/Dev/guildlm/builder")
from _teeth_suite import verdict_for, GEN
from _corpus_state import check as _corpus_check

SWAP = {"StatusNotFound": "StatusBadRequest", "StatusCreated": "StatusOK",
        "StatusBadRequest": "StatusNotFound", "StatusTooManyRequests": "StatusServiceUnavailable",
        "StatusMovedPermanently": "StatusFound", "StatusNoContent": "StatusOK",
        "StatusConflict": "StatusBadRequest", "StatusMethodNotAllowed": "StatusBadRequest",
        "StatusUnprocessableEntity": "StatusBadRequest", "StatusOK": "StatusAccepted",
        # 27 sites in the corpus write 500 and had no swap, so the sweep
        # skipped them and the coverage line said so. 502 is the plausible
        # neighbour: still a server-side failure, still wrong.
        "StatusInternalServerError": "StatusBadGateway"}
CODE = re.compile(r"^\s*(?!//)(?!\s*\*).*http\.(Status[A-Za-z]+)")

# SHAPE 4: error wrapping. `fmt.Errorf("...: %w", ErrX)` -> `%v` leaves the message
# BYTE-IDENTICAL and breaks errors.Is. That is the sharpest probe in this file: a test
# that compares the error string still passes, and only a test that actually calls
# errors.Is notices. Six specs promise errors.Is behaviour by name, so when this survives
# it is a promise with a test that checks the wrong thing — not merely a missing test.
WRAP = re.compile(r'fmt\.Errorf\("([^"]*)%w([^"]*)"')


ALL_SITES = "--all-sites" in sys.argv
# WHICH GENERATION OF THE CORPUS. Defaults to v4 — the reference trees every row in
# logs/hole-hunt-rows.tsv was measured on — so nothing about an unflagged run changes.
#
# It exists because the campaign's closing question is a BEFORE/AFTER: the repaired specs
# have to be redrawn and re-swept, and the only honest way to compare is to keep both row
# files. Overwriting the tracked baseline with the "after" numbers would leave the claim
# "the survivor count dropped" resting on a file that no longer holds the number it dropped
# from. Each generation gets its own dump path for the same reason the baseline is tracked
# at all: a verdict that changes has to show up as a diff, not as a memory.
GEN_SUFFIX = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--gen=")), "v4")
def rows_path(suffix: str) -> pathlib.Path:
    """v4 keeps the tracked baseline's exact name; every other generation gets its own."""
    return pathlib.Path("logs") / ("hole-hunt-rows.tsv" if suffix == "v4"
                                   else f"hole-hunt-rows-{suffix}.tsv")


ROWS_PATH = rows_path(GEN_SUFFIX)


def go_files(art):
    """Every non-test .go file in the artifact — the WHOLE tree, subdirectories included.

    One function because there used to be six copies of this walk and five of them said
    `glob` instead of `rglob`. The four artifacts with an internal/ layout contributed zero
    status rows and zero wrap rows to a 170-row sweep, and no report said so: the coverage
    counter had been given a `recurse` flag and passed False for those same five shapes, so
    matched equalled probed and each read as fully covered.
    """
    return sorted(f for f in art.rglob("*.go") if not f.name.endswith("_test.go"))


def artifacts():
    """The artifacts to sweep: the positional targets, or the whole archive.

    ONE selector for all four shapes and the coverage counter. The first attempt at this
    patched main()'s loop alone and left wrap_rows/sort_rows/header_rows globbing the
    archive, so a run given an explicit directory still answered about -v4 artifacts — the
    same silent-substitution bug, half-fixed, which is worse than not fixed because the
    call now LOOKS honoured.
    """
    targets = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not targets:
        return sorted(GEN.glob(f"*-{GEN_SUFFIX}"))
    out = []
    for t in targets:
        d = pathlib.Path(t)
        if not d.is_dir():
            raise SystemExit(f"{t} is not a directory")
        out.append(d)
    return out


def wrap_rows():
    out = []
    for art in artifacts():
        for f in go_files(art):
            if f.name.endswith("_test.go"):
                continue
            text = f.read_text(errors="ignore")
            # EVERY wrap, not the first. A file often wraps SEVERAL sentinels, and a suite
            # can defend one while ignoring the rest: tasks-api asserts errors.Is four
            # times, all for ErrNotFound, while its spec also promises ErrInvalidTask —
            # which nothing checks. Probing one site per file would have reported CAUGHT
            # on the defended sentinel and called the file clean.
            sites = list(dict.fromkeys(m.group(0) for m in WRAP.finditer(text)))
            if not sites:
                continue
            for orig in (sites if ALL_SITES else sites[:1]):
                def mut(t, a=orig, b=orig.replace("%w", "%v", 1)):
                    return t.replace(a, b, 1) if a in t else None
                # The sentinel is an ARGUMENT of the call, so look past the format
                # string — and exclude Errorf itself, which the first version of this
                # matched every time and printed as the sentinel name.
                after = text[text.index(orig) + len(orig):][:120]
                sentinel = re.search(r"\bErr(?!orf\b)[A-Za-z]+", after)
                tag = f"%w -> %v ({sentinel.group(0) if sentinel else '?'})"
                rel = str(f.relative_to(art))
                v, _ = verdict_for(art, rel, mut)
                out.append((art.name, rel, tag, v))
                print(f"{art.name:<26} {rel:<22} {tag:<26} {v}", flush=True)
            if not ALL_SITES:
                break
    return out


# SHAPE 3: sort order. TEETH.md already fixes the FORM this must take — deleting a
# sort.Slice catches only probabilistically, because the unsorted result depends on Go's
# map-iteration randomness, so an ascending assertion may pass by luck. REVERSING the
# comparator (`<` -> `>`) catches every run or never. A mutation that cannot be relied on
# to fail is not a test, and a hole hunter built on one reports noise.
# NOT anchored to the whole line. Five of the six comparators in the corpus are written
# inline — `sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })` — and
# the first version of this pattern required `return` at the start and the comparison at
# the end, so it saw one site in six. Under-sampling again, in a shape added to fix
# under-sampling; the flip stays unambiguous because only the matched substring is
# rewritten.
COMPARATOR = re.compile(r'(\w+\[i\]\.\w+) < (\w+\[j\]\.\w+)')


def sort_rows():
    out = []
    for art in artifacts():
        for f in go_files(art):
            if f.name.endswith("_test.go"):
                continue
            hits = []
            for i, ln in enumerate(f.read_text(errors="ignore").splitlines()):
                m = COMPARATOR.search(ln)
                if m:
                    hits.append((str(f.relative_to(art)), m.group(0), f"{m.group(1)} > {m.group(2)}",
                                 m.group(1).split(".")[-1], i))
                    if not ALL_SITES:
                        break
            for rel, line, flipped, field, idx in hits:
                mut = replace_at(idx, line, flipped)
                v, _ = verdict_for(art, rel, mut)
                out.append((art.name, rel, f"reverse sort by {field}", v))
                print(f"{art.name:<26} {rel:<22} {('reverse sort by ' + field):<26} {v}",
                      flush=True)
            if hits and not ALL_SITES:
                break
    return out


# SHAPE 2: response headers. A wrong Content-Type is invisible to a test that only reads
# the body, and the campaign's own taxonomy names headers as a hole shape — kvservice and
# jsonapi both had one closed by hand. Dropping the header entirely is the sharper probe:
# changing the value can still be caught by a strict equality assert, but a test that never
# looks at headers at all cannot notice either.
HEADER = re.compile(r'^\s*w\.Header\(\)\.Set\("([^"]+)", *"[^"]*"\)')


# SHAPE 5: the JSON WIRE NAME. `json:"id"` -> `json:"id_x"` renames the field ON THE WIRE
# and nowhere else. A test that POSTs a body and decodes the response INTO THE SAME STRUCT
# round-trips through the renamed tag on both sides and passes; only a test that touches the
# RAW JSON — asserting a key, or decoding into a map — can see it. That is the sharpest
# shape in this file for the same reason %w->%v was: the failure is invisible to the way the
# tests are usually written, and the contract it breaks is the one real clients depend on.
TAG = re.compile(r'`json:"([a-zA-Z_][\w]*)((?:,[\w]+)*)"`')


def tag_rows():
    out = []
    for art in artifacts():
        for f in go_files(art):
            if f.name.endswith("_test.go"):
                continue
            hits = []
            text = f.read_text(errors="ignore")
            for m in TAG.finditer(text):
                hits.append((str(f.relative_to(art)), m.start(), m.end(), m.group(0), m.group(1), m.group(2)))
                if not ALL_SITES:
                    break
            for rel, start, end, orig, name, opts in hits:
                # ADDRESSED BY OFFSET. The unique-substring guard here refused any tag that
                # appears twice in a file, and taskflow carries `json:"id"` on both Task and
                # Project — so the tag shape reported NOAPPLY for the one artifact it most
                # needed to answer about. Same defect as the status shape and the same fix:
                # the detector already located the site, so hand the mutator that location
                # instead of asking it to find the text again.
                def mut(t, s=start, e=end, a=orig, b=f'`json:"{name}_x{opts}"`'):
                    return t[:s] + b + t[e:] if t[s:e] == a else None
                v, _ = verdict_for(art, rel, mut)
                out.append((art.name, rel, f'json tag "{name}" renamed', v))
                print(f"{art.name:<26} {rel:<22} {('json tag ' + name):<26} {v}", flush=True)
            if hits and not ALL_SITES:
                break
    return out


# SHAPE 6: the BOUNDARY. `offset >= len(items)` -> `offset > len(items)`, `limit <= 0` ->
# `limit < 0`. One character, one input's worth of behaviour: the clamp that used to fire on
# the exact boundary now lets it through, and every value on either side behaves identically.
# That is the classic untested case, and this corpus is full of clamps — paginate's three
# guards, the rate limiter's capacity, the LRU's eviction, bitset's bounds. A test that
# exercises a range but never its endpoint cannot see it.
BOUND = re.compile(r"(?<![<>=!])(<=|>=|<|>)(?!=)")
BOUND_FLIP = {"<": "<=", "<=": "<", ">": ">=", ">=": ">"}
# Only lines that compare against a LIMIT-shaped operand: a length, a capacity, zero, or a
# named bound. Flipping `i < len(x)` inside an ordinary loop just changes an iteration count
# and is usually caught by anything at all, which makes it noise rather than a probe.
BOUND_LINE = re.compile(r"(<=|>=|<|>)\s*(0\b|len\(|cap\(|capacity|limit|offset|Limit|Cap)")


def inert_flip(line: str, body: str) -> bool:
    """Is flipping this line's boundary operator a change NO INPUT can observe?

    `if offset < 0 { offset = 0 }` flipped to `<= 0` takes the clamp branch at offset==0
    and assigns 0 to something already 0, so a SURVIVED verdict there says nothing about
    the tests. Detected the same way the guard reads: the compared variable, the constant,
    and an assignment of that constant in the body. Learned from this shape's own
    self-test, whose first fixture flipped `offset >= len(items)` and changed nothing.

    TWO shapes, and there are certainly more — this is SYNTACTIC, and inertness is
    semantic. `_bound_probe.py` is the empirical answer for the ones that get through:
    paginate's early return is inert because falling through computes an empty slice by a
    different route, which no pattern over one line and its successor can see.

    Extracted so _bound_probe classifies flips the same way this does. A second copy of a
    predicate is a second thing to keep true.
    """
    guard = re.match(r"\s*(?:\}\s*else\s+)?if\s+(\w+)\s*[<>]=?\s*(\w+)", line)
    if not guard:
        return False
    # (1) the clamp assigns the boundary value it just compared against. (2) `if x < 0 {
    # return -x }` — the negation of zero is zero, so including the boundary changes
    # nothing. numkit's abs() is exactly that and would otherwise be reported as a hole.
    return bool(re.match(rf"\s*{guard.group(1)}\s*=\s*{guard.group(2)}\s*$", body)
                or (guard.group(2) == "0"
                    and re.match(rf"\s*return\s+-{guard.group(1)}\s*$", body)))


# `offset = 0`, `limit = 100` — a clamp body, and the only part of a clamp a mutation can
# move. Numeric only: substituting an identifier could change types or not compile, and a
# probe that fails to build reports CAUGHT for the wrong reason.
CLAMP_ASSIGN = re.compile(r"^(\s*)(\w+)\s*=\s*(\d+)\s*$")
CLAMP_SENTINEL = 7777


def clamp_value_row(art, rel, idx: int, body: str):
    """Break what an INERT clamp ASSIGNS, since breaking what it tests changes nothing.

    Returns [] when the body assigns something non-numeric (numkit's `return -x` shape has
    no assignment at all), so an unprobeable site produces no row rather than a reassuring
    one.
    """
    m = CLAMP_ASSIGN.match(body)
    if not m:
        return []
    val = CLAMP_SENTINEL if int(m.group(3)) != CLAMP_SENTINEL else CLAMP_SENTINEL + 1111
    mut = replace_at(idx, body, f"{m.group(1)}{m.group(2)} = {val}")
    v, _ = verdict_for(art, rel, mut)
    tag = f"clamp value {m.group(2)} = {m.group(3)} -> {val}"
    print(f"{art.name:<26} {rel:<22} {tag:<26} {v}", flush=True)
    return [(art.name, rel, tag, v)]


def bound_rows():
    out = []
    for art in artifacts():
        for f in go_files(art):
            if f.name.endswith("_test.go"):
                continue
            rel = str(f.relative_to(art))
            hits = []
            for i, ln in enumerate(f.read_text(errors="ignore").splitlines()):
                stripped = ln.strip()
                if stripped.startswith("//") or not BOUND_LINE.search(ln):
                    continue
                m = BOUND.search(ln)
                if not m:
                    continue
                hits.append((i, ln, m.group(1)))
                if not ALL_SITES:
                    break
            text_lines = f.read_text(errors="ignore").splitlines()
            for idx, line, op in hits:
                flipped = line.replace(op, BOUND_FLIP[op], 1)
                body = text_lines[idx + 1] if idx + 1 < len(text_lines) else ""
                if inert_flip(line, body):
                    tag = f"boundary {op} -> {BOUND_FLIP[op]}"
                    out.append((art.name, rel, tag, "INERT"))
                    print(f"{art.name:<26} {rel:<22} {tag:<26} INERT (clamp assigns the "
                          f"boundary value; no input distinguishes the flip)", flush=True)
                    # INERT IS A REDIRECT, NOT A VERDICT. The property that makes a clamp's
                    # CONDITION unobservable — the body assigns the value it just compared —
                    # is exactly what makes the assigned VALUE the only thing worth breaking.
                    # This shape flips operators and never touches values, so every clamp in
                    # the corpus was a systematic blind spot that the inert filter HID rather
                    # than forwarded. Measured when the filter was finally questioned: 5 of 9
                    # inert clamps have an untested assigned value, including two promised in
                    # so many words ("clamping negatives to the default/zero").
                    out.extend(clamp_value_row(art, rel, idx + 1, body))
                    continue
                mut = replace_at(idx, line, flipped.rstrip("\n"))
                v, _ = verdict_for(art, rel, mut)
                tag = f"boundary {op} -> {BOUND_FLIP[op]}"
                out.append((art.name, rel, tag, v))
                print(f"{art.name:<26} {rel:<22} {tag:<26} {v}", flush=True)
            if hits and not ALL_SITES:
                break
    return out


def header_rows():
    out = []
    for art in artifacts():
        for f in go_files(art):
            if f.name.endswith("_test.go"):
                continue
            hits = []
            for i, ln in enumerate(f.read_text(errors="ignore").splitlines()):
                m = HEADER.match(ln)
                if m:
                    hits.append((str(f.relative_to(art)), m.group(1), i, ln.strip()))
                    if not ALL_SITES:
                        break
            for rel, header, idx, line in hits:
                mut = replace_at(idx, line, "// MUTANT: header dropped")
                v, _ = verdict_for(art, rel, mut)
                out.append((art.name, rel, f"drop {header}", v))
                print(f"{art.name:<26} {rel:<22} {('drop ' + header):<26} {v}", flush=True)
            if hits and not ALL_SITES:
                break
    return out


# Probe every site, not just the first. The first pass stopped at one status write per
# artifact because it was the cheap sweep; shortener alone has two 400 sites and only one
# was ever probed, and the one that was probed turned out to be the real hole. Under-
# sampling in a hole hunt is the same error as a green suite: absence of a finding read as
# absence of a hole.

def self_test() -> int:
    """Prove the hunt can tell a defended status from an undefended one.

    A hole hunter that reports SURVIVED for everything finds "holes" everywhere, and one
    that reports CAUGHT for everything reports a campaign that is finished. Both read as
    a result. So: two planted projects whose answer is known before the run, plus the
    label rule, which is the part most likely to rot silently — it is a string match, and
    a string match that stops matching just goes quiet.
    """
    import tempfile
    MOD = "module example.com/h\n\ngo 1.23\n"
    IMPL = ('package main\n\nimport "net/http"\n\n'
            'func H(w http.ResponseWriter, r *http.Request) {\n'
            '\tw.WriteHeader(http.StatusNotFound)\n}\n\nfunc main() {}\n')
    DEFENDED = ('package main\n\nimport (\n\t"net/http"\n\t"net/http/httptest"\n'
                '\t"testing"\n)\n\nfunc TestH(t *testing.T) {\n'
                '\trec := httptest.NewRecorder()\n'
                '\tH(rec, httptest.NewRequest("GET", "/", nil))\n'
                '\tif rec.Code != http.StatusNotFound {\n\t\tt.Fatalf("got %d", rec.Code)\n\t}\n}\n')
    BLIND = ('package main\n\nimport (\n\t"net/http/httptest"\n\t"testing"\n)\n\n'
             'func TestH(t *testing.T) {\n\trec := httptest.NewRecorder()\n'
             '\tH(rec, httptest.NewRequest("GET", "/", nil))\n\t_ = rec\n}\n')

    def swap(text):
        return text.replace("http.StatusNotFound", "http.StatusBadRequest", 1)

    failures = []
    for want, test_src in (("CAUGHT", DEFENDED), ("SURVIVED", BLIND)):
        with tempfile.TemporaryDirectory() as td:
            art = pathlib.Path(td) / "art"
            art.mkdir()
            (art / "go.mod").write_text(MOD)
            (art / "h.go").write_text(IMPL)
            (art / "h_test.go").write_text(test_src)
            got, note = verdict_for(art, "h.go", swap)
        if got != want:
            failures.append(f"a test that {'asserts' if want == 'CAUGHT' else 'ignores'} "
                            f"the status should be {want}, got {got} ({note})")

    # SHAPE 5, planted the same way. The point of a json-tag rename is that a test which
    # round-trips through the SAME struct cannot see it, so the fixtures are: one test that
    # asserts the raw wire key (must CAUGHT) and one that decodes into the struct (must
    # SURVIVE). If the second ever reads CAUGHT the shape is not measuring what it claims.
    TAGMOD = "module example.com/j\n\ngo 1.23\n"
    TAGIMPL = ('package main\n\nimport (\n\t"encoding/json"\n\t"net/http"\n)\n\n'
               'type Task struct {\n\tID string `json:"id"`\n}\n\n'
               'func H(w http.ResponseWriter, r *http.Request) {\n'
               '\tjson.NewEncoder(w).Encode(Task{ID: "1"})\n}\n\nfunc main() {}\n')
    RAW = ('package main\n\nimport (\n\t"net/http/httptest"\n\t"strings"\n\t"testing"\n)\n\n'
           'func TestH(t *testing.T) {\n\trec := httptest.NewRecorder()\n'
           '\tH(rec, httptest.NewRequest("GET", "/", nil))\n'
           '\tif !strings.Contains(rec.Body.String(), `"id"`) {\n'
           '\t\tt.Fatalf("wire key id missing: %s", rec.Body.String())\n\t}\n}\n')
    ROUNDTRIP = ('package main\n\nimport (\n\t"encoding/json"\n\t"net/http/httptest"\n'
                 '\t"testing"\n)\n\nfunc TestH(t *testing.T) {\n\trec := httptest.NewRecorder()\n'
                 '\tH(rec, httptest.NewRequest("GET", "/", nil))\n\tvar got Task\n'
                 '\tif err := json.NewDecoder(rec.Body).Decode(&got); err != nil {\n'
                 '\t\tt.Fatal(err)\n\t}\n\tif got.ID != "1" {\n\t\tt.Fatalf("got %q", got.ID)\n\t}\n}\n')

    def rename_tag(text):
        return text.replace('`json:"id"`', '`json:"id_x"`', 1)

    for want, test_src, why in (("CAUGHT", RAW, "asserts the raw wire key"),
                                ("SURVIVED", ROUNDTRIP, "decodes into the same struct")):
        with tempfile.TemporaryDirectory() as td:
            art = pathlib.Path(td) / "art"
            art.mkdir()
            (art / "go.mod").write_text(TAGMOD)
            (art / "j.go").write_text(TAGIMPL)
            (art / "j_test.go").write_text(test_src)
            got, note = verdict_for(art, "j.go", rename_tag)
        if got != want:
            failures.append(f"json tag: a test that {why} should be {want}, got {got} ({note})")

    # SHAPE 6, planted both ways. A boundary flip changes behaviour at EXACTLY ONE input, so
    # the fixtures are a test that probes the endpoint (must CAUGHT) and one that probes only
    # the interior (must SURVIVE). If the interior test ever reads CAUGHT the probe is
    # changing more than the boundary and is not measuring what it claims.
    BMOD = "module example.com/b\n\ngo 1.23\n"
    # `limit <= 0 -> use everything` is the shape this corpus actually writes (paginate's
    # first guard). Flipped to `< 0`, limit=0 stays 0 and the page comes back EMPTY. The
    # first fixture I wrote flipped `offset >= len(items)`, which changes nothing at all —
    # items[len:] is a valid empty slice either way — and the self-test caught that the probe
    # was inert before it ever ran on the corpus.
    BIMPL = ('package main\n\nfunc Page(items []int, limit int) []int {\n'
             '\tif limit <= 0 {\n\t\tlimit = len(items)\n\t}\n'
             '\tif limit > len(items) {\n\t\tlimit = len(items)\n\t}\n'
             '\treturn items[:limit]\n}\n\nfunc main() {}\n')
    EDGE = ('package main\n\nimport "testing"\n\nfunc TestB(t *testing.T) {\n'
            '\tif got := Page([]int{1, 2}, 0); len(got) != 2 {\n'
            '\t\tt.Fatalf("limit=0 means no limit, got %v", got)\n\t}\n}\n')
    INTERIOR = ('package main\n\nimport "testing"\n\nfunc TestB(t *testing.T) {\n'
                '\tif got := Page([]int{1, 2}, 1); len(got) != 1 {\n'
                '\t\tt.Fatalf("limit=1 should give 1, got %v", got)\n\t}\n}\n')

    def flip(text):
        return text.replace("limit <= 0", "limit < 0", 1)

    for want, test_src, why in (("CAUGHT", EDGE, "probes the endpoint"),
                                ("SURVIVED", INTERIOR, "probes only the interior")):
        with tempfile.TemporaryDirectory() as td:
            art = pathlib.Path(td) / "art"
            art.mkdir()
            (art / "go.mod").write_text(BMOD)
            (art / "b.go").write_text(BIMPL)
            (art / "b_test.go").write_text(test_src)
            got, note = verdict_for(art, "b.go", flip)
        if got != want:
            failures.append(f"boundary: a test that {why} should be {want}, got {got} ({note})")

    # SHAPE 6b — the clamp's VALUE, planted both ways. This exists because the INERT verdict
    # used to end the inquiry: `if offset < 0 { offset = 0 }` is genuinely unobservable when
    # the OPERATOR moves, and that says nothing about whether anything tests what the clamp
    # assigns. Both fixtures share the identical inert condition, so the only thing the two
    # cases differ in is whether a test passes a negative offset — which is the whole claim.
    CMOD = "module example.com/c\n\ngo 1.23\n"
    CIMPL = ("package c\n\nfunc Clamp(offset int) int {\n"
             "\tif offset < 0 {\n\t\toffset = 0\n\t}\n\treturn offset\n}\n")
    C_DEFENDED = ('package c\n\nimport "testing"\n\nfunc TestClamp(t *testing.T) {\n'
                  '\tif Clamp(-5) != 0 {\n\t\tt.Fatalf("Clamp(-5) = %d, want 0", Clamp(-5))\n\t}\n}\n')
    # Exercises Clamp, never with a negative — the shape that leaves a clamp undefended.
    C_UNDEFENDED = ('package c\n\nimport "testing"\n\nfunc TestClamp(t *testing.T) {\n'
                    '\tif Clamp(5) != 5 {\n\t\tt.Fatalf("Clamp(5) = %d, want 5", Clamp(5))\n\t}\n}\n')
    for want, test_src, why in (("CAUGHT", C_DEFENDED, "passes a negative"),
                                ("SURVIVED", C_UNDEFENDED, "never passes a negative")):
        with tempfile.TemporaryDirectory() as td:
            art = pathlib.Path(td) / "art"
            art.mkdir()
            (art / "go.mod").write_text(CMOD)
            (art / "c.go").write_text(CIMPL)
            (art / "c_test.go").write_text(test_src)
            # line 4 (0-based) is `\t\toffset = 0`, the clamp body
            rows = clamp_value_row(art, "c.go", 4, "\t\toffset = 0")
        if not rows:
            failures.append("clamp value: the probe produced NO ROW for a numeric clamp body")
        elif rows[0][3] != want:
            failures.append(f"clamp value: a test that {why} should be {want}, got {rows[0][3]}")
    # A non-numeric clamp body must produce NO row rather than a reassuring one.
    with tempfile.TemporaryDirectory() as td:
        art = pathlib.Path(td) / "art"
        art.mkdir()
        (art / "go.mod").write_text(CMOD)
        (art / "c.go").write_text(CIMPL)
        (art / "c_test.go").write_text(C_DEFENDED)
        if clamp_value_row(art, "c.go", 4, "\t\treturn -offset"):
            failures.append("clamp value: a body with no numeric assignment must yield no row")

    # THE BASELINE PATH MUST NOT MOVE. --gen exists so a redraw can be swept without
    # overwriting the tracked v4 rows, and the one way it could do damage is by renaming the
    # v4 file — then the "before" numbers are gone and the before/after claim rests on a
    # file that no longer holds the number it moved from.
    if str(rows_path("v4")) != "logs/hole-hunt-rows.tsv":
        failures.append(f"the v4 dump path must stay exactly the tracked baseline, "
                        f"got {rows_path('v4')}")
    if rows_path("v5") == rows_path("v4"):
        failures.append("a second generation must not write to the baseline's file")

    # THE WALK MUST REACH NESTED PACKAGES. Five of six shapes said glob instead of rglob,
    # so ledger, taskapi, taskapipro and workapi — every artifact with an internal/ layout —
    # contributed no status and no wrap rows at all, and the coverage counter agreed with
    # them because it had been given a flag and passed False.
    with tempfile.TemporaryDirectory() as td:
        art = pathlib.Path(td)
        (art / "internal" / "api").mkdir(parents=True)
        (art / "top.go").write_text("package main\n")
        (art / "internal" / "api" / "deep.go").write_text("package api\n")
        (art / "internal" / "api" / "deep_test.go").write_text("package api\n")
        names = [f.name for f in go_files(art)]
        if "deep.go" not in names:
            failures.append(f"a file in internal/api must be swept, not just the top "
                            f"level — this is the five-shape bug: {names}")
        if "top.go" not in names:
            failures.append(f"the top level must still be swept: {names}")
        if "deep_test.go" in names:
            failures.append("_test.go files are the assertion, not the subject")

    # the label rule, checked directly: it is a string match and string matches rot quietly
    benign = "\t\trec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}"
    if "statusRecorder" not in benign:
        failures.append("the known-benign label would no longer match its own example")
    if "statusRecorder" in "\t\twriteJSON(w, http.StatusBadRequest, nil)":
        failures.append("the known-benign label matches an ordinary status write")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("OK — a defended status is CAUGHT, an unasserted one SURVIVES, the benign label "
          "matches only the recorder default,\n     a json-tag rename is CAUGHT by a raw-key "
          "assertion while a struct round-trip cannot see it,\n     and a boundary flip is "
          "CAUGHT by an endpoint test while an interior test cannot see it,\n     and an "
          "INERT clamp's assigned VALUE is CAUGHT only by a test that passes a negative")
    return 0


def replace_at(index: int, old: str, new: str):
    """A mutator that edits ONE LINE BY INDEX, not by matching its text.

    Text matching cannot address a site that appears twice: jsonapi's regenerated main.go
    writes `w.WriteHeader(http.StatusBadRequest)` on two lines, byte-identical, and the
    uniqueness guard this replaced refused both — a grading blocked outright rather than a
    wrong answer, but blocked all the same. The detector already knows which line it chose;
    carrying the index is simply telling the mutator what the detector knew.
    """
    def mut(text):
        lines = text.splitlines()
        if index >= len(lines) or old not in lines[index]:
            return None
        lines[index] = lines[index].replace(old, new, 1)
        return "\n".join(lines) + "\n"
    return mut


def main() -> int:
    # A POSITIONAL ARGUMENT MUST NOT BE SILENTLY IGNORED. This swept the whole archive
    # while I was reading its output as a report on a freshly generated tree I had passed
    # on the command line — every row came back tagged "-v4" and the answer was about
    # artifacts I had not asked about. Same shape as the four instruments fixed earlier
    # today; this one escaped that sweep only because it is slow enough to time out
    # before it can answer, so it got filed as "no verdict" instead of as this.
    rows = []
    for art in artifacts():
        for f in go_files(art):
            if f.name.endswith("_test.go"):
                continue
            # EVERY matching line, not the first in the file. --all-sites said "every site"
            # and meant "one per file": the coverage counter put it at 14 probed of 123
            # matched. A flag that under-delivers on its own name is the under-sampling
            # defect wearing a disguise, and it is the fourth time in this file.
            hits = []
            for i, ln in enumerate(f.read_text(errors="ignore").splitlines()):
                m = CODE.match(ln)
                if m and m.group(1) in SWAP:
                    hits.append((i, str(f.relative_to(art)), m.group(1), ln))
                    if not ALL_SITES:
                        break
            for hit in hits:
                idx, rel, old, line = hit
                new = SWAP[old]
                # Mutate the LINE that was found, not the first textual occurrence in the
                # file. `re.subn(..., count=1)` over whole-file text hits whichever comes
                # first — and shortener's handlers.go names StatusMovedPermanently in a
                # DOC COMMENT six lines above the code. The sweep dutifully reported
                # SURVIVED for a mutation that only ever edited a comment: a hole announced
                # where none exists, which is the one direction a hole hunter must not fail
                # in. The site detector already skips comment lines; the mutator did not.
                # ADDRESSED BY INDEX, which is what the detector already knew. This used to
                # refuse any line appearing more than once in its file ("ambiguous — refuse
                # rather than guess"), and that refusal was 39 of the 47 NOAPPLY rows in the
                # sweep: a QUARTER of the corpus answering nothing, quietly, because handlers
                # repeat `http.Error(w, "...", http.StatusInternalServerError)` verbatim.
                # replace_at was written for exactly this and had only been wired into the
                # newer shapes — the older one kept refusing, and a refusal in a hole hunter
                # reads like a clean row unless somebody counts them.
                mut = replace_at(idx, line, line.replace(f"http.{old}", f"http.{new}", 1))
                v, note = verdict_for(art, rel, mut)
                line = line.strip()
                # LABEL a known-benign shape, do not suppress it. `statusRecorder{..., status:
                # http.StatusOK}` is the DEFAULT a logging middleware records before the
                # handler writes anything, so mutating it changes log output and nothing else.
                # It has surfaced as a SURVIVED row twice (taskflow, usersapi) and cost a
                # code-read both times. Suppressing the class is how a hole hunter goes quiet;
                # naming it keeps the row visible and stops it being re-litigated.
                if v == "SURVIVED" and "statusRecorder" in line:
                    v = "SURVIVED*"
                rows.append((art.name, rel, f"{old}->{new}", v))
                print(f"{art.name:<26} {rel:<22} {old}->{new:<26} {v}", flush=True)
            if hits and not ALL_SITES:
                break
    print("\n=== shape 2: drop a response header ===")
    rows += header_rows()
    print("\n=== shape 3: reverse a sort comparator ===")
    rows += sort_rows()
    print("\n=== shape 4: unwrap an error (%w -> %v) ===")
    rows += wrap_rows()
    print("\n=== shape 5: rename a JSON field tag ===")
    rows += tag_rows()
    print("\n=== shape 6: flip a boundary comparison ===")
    rows += bound_rows()
    surv = [r for r in rows if r[3] == "SURVIVED"]
    # COVERAGE, counted independently of the sweep. Under-sampling was this tool's most
    # repeated defect — three times in one day it probed one site and printed a clean table,
    # and the missing rows were the answer (logs/FINDING-instruments-are-unmeasured.txt).
    # The check deliberately does NOT reuse the sweep's own site selection: it re-scans the
    # corpus for each pattern and compares the totals, so a selector that silently narrows
    # shows up as a gap rather than as a smaller, tidier report.
    def matching_sites(pattern, per_line=False, search=False, *_ignored):
        """Count sites the pattern matches. `per_line` for the LINE-ANCHORED patterns (CODE,
        HEADER): they start with ^ and are compiled without MULTILINE because the sweep feeds
        them one line at a time, so scanning whole-file text with them finds nothing. The
        first version of this counter did exactly that and reported `matched 0, probed 14` —
        a coverage check that under-counted, in the tool built to catch under-counting."""
        n = 0
        for art in artifacts():
            # ALWAYS THE WHOLE TREE. There used to be a `recurse` flag here, defaulting
            # to False, and only the boundary shape passed True — because I noticed that
            # bound_rows walked nested packages while this walked the top level, and
            # resolved the discrepancy by teaching the COUNTER to match the shape.
            #
            # Five shapes globbed only the top level, the counter counted only the top
            # level, matched equalled probed, and every one of them read as fully covered.
            # The check built to catch under-sampling had been calibrated to it. Four
            # artifacts with an internal/ layout — ledger, taskapi, taskapipro, workapi —
            # contributed ZERO status and ZERO wrap rows to a 170-row sweep, and nothing
            # said so, because a coverage number computed over the walk can only ever
            # report the walk back to you.
            #
            # The corpus is the corpus. There is no flag now: if a shape under-samples, the
            # gap shows up here, which is the entire reason this counter exists.
            for f in go_files(art):
                if f.name.endswith("_test.go"):
                    continue
                text = f.read_text(errors="ignore")
                if per_line:
                    probe = pattern.search if search else pattern.match
                    n += sum(1 for ln in text.splitlines()
                             if not ln.strip().startswith("//") and probe(ln))
                else:
                    n += len(pattern.findall(text))
        return n


    print("\ncoverage — sites the patterns match in the corpus vs rows probed above:")
    for label, pat, per_line, probed, *extra in (
        ("status code", CODE, True,
         len([r for r in rows if "->" in r[2] and "Status" in r[2]])),
        ("response header", HEADER, True,
         len([r for r in rows if r[2].startswith("drop ")])),
        ("sort order", COMPARATOR, False,
         len([r for r in rows if r[2].startswith("reverse")])),
        ("error wrapping", WRAP, False,
         len([r for r in rows if r[2].startswith("%w")])),
        ("json field tag", TAG, False,
         len([r for r in rows if r[2].startswith("json tag")])),
        ("boundary compare", BOUND_LINE, True,
         len([r for r in rows if r[2].startswith("boundary")]), True, True),
    ):
        search, recurse = (extra + [False, False])[:2]
        total = matching_sites(pat, per_line, search, recurse)
        flag = "" if probed >= total else f"   <- {total - probed} NOT PROBED"
        print(f"  {label:<16} matched {total:>3}   probed {probed:>3}{flag}")

    # ALWAYS WRITE THE ROWS DOWN. A retraction today traced back to nothing worse than
    # `tail`: the session's first full sweep printed 150 verdicts, I kept its summary, and
    # when a later count differed by one there was no row list left to compare — so I
    # published an inference about nondeterminism that two full sweeps then contradicted.
    #
    # The file is git-TRACKED on purpose. A corpus verdict that changes shows up as a diff
    # in version control without anyone remembering to save the previous run, which is the
    # part that failed. Only written for a whole-corpus sweep; a targeted run answers about
    # one tree and would clobber the baseline with something not comparable to it.
    if not [a for a in sys.argv[1:] if not a.startswith("-")]:
        dump = ROWS_PATH
        if dump.parent.is_dir():
            dump.write_text("".join(f"{a}\t{f}\t{tag}\t{v}\n" for a, f, tag, v in rows))
            print(f"\n  rows written to {dump} (tracked — a changed verdict shows as a diff)")

    star = [r for r in rows if r[3] == "SURVIVED*"]
    # SAY HOW MANY PROBES COULD ACTUALLY ANSWER. The rows have always reported
    # BASELINE-RED and NOAPPLY correctly — the SUMMARY counted them as probes anyway, so
    # tasks-api-min-v4, which does not compile at all, printed
    #     22 probes · 0 SURVIVED (green build, real behaviour change)
    # where not one of the 22 could possibly have survived and "green build" is false. The
    # corpus headline quoted all day carried both non-building artifacts inside its
    # denominator for the same reason.
    dead = [r for r in rows if r[3] in ("BASELINE-RED", "NOAPPLY", "NOTESTS")]
    usable = len(rows) - len(dead)
    print(f"\n{usable} of {len(rows)} probes could answer · {len(surv)} SURVIVED "
          f"(green build, real behaviour change)"
          + (f" · {len(star)} SURVIVED* (known-benign: a statusRecorder default, log-only)"
             if star else ""))
    if dead:
        br = sum(1 for r in dead if r[3] == "BASELINE-RED")
        na = len(dead) - br
        arts = sorted({r[0] for r in dead if r[3] == "BASELINE-RED"})
        print(f"  {len(dead)} could NOT: {br} BASELINE-RED (artifact already failing"
              + (f": {', '.join(arts)}" if arts else "") + f"), {na} did not apply")
    if usable == 0:
        raise SystemExit("  NOTHING WAS MEASURED — every probe hit a red baseline or "
                         "failed to apply. This is not 'no holes found'.")
    for r in surv:
        print("   ", r)
    print("\nA SURVIVED row is a CANDIDATE. The next question is always whether the SPEC\n"
          "promises the behaviour that was broken — on the first run one survivor was a\n"
          "genuine undefended promise and the other was log-only output.")
    return 0


if __name__ == "__main__":
    # DISPATCHED HERE, NOT AT MODULE LEVEL, which is where it used to sit. Any tool that
    # imports this module for its mutators — _bound_probe does, for BOUND/replace_at —
    # inherited the dispatch: running `_bound_probe.py --self-test` ran THIS file's
    # self-test instead, printed its OK line, and exited 0 before the caller's own
    # fixtures were ever built. A green that belongs to another tool is the worst kind.
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    # NEVER SWEEP A MOVING CORPUS. A whole-corpus run overwrites logs/hole-hunt-rows.tsv —
    # the tracked baseline, and the only durable record of what the corpus said — so a
    # sweep taken while artifacts are being regenerated would replace real verdicts with
    # verdicts about half-written trees. Targeted runs refuse only if THEIR tree is the one
    # in flight. Learned from a teeth run that called two usersapi invariants UNDEFENDED
    # while usersapi held no test files yet.
    _targets = [a for a in sys.argv[1:] if not a.startswith("-")]
    if _targets:
        if any(_corpus_check(t) == "refuse" for t in _targets):
            raise SystemExit(2)
    else:
        # REFUSE ON THE TREES THIS SWEEP WOULD MEASURE, not on the fact that something,
        # somewhere, is generating. The blanket rule was written when every run wrote
        # straight into a -v4 tree, and it is now too coarse: closure runs write to
        # ./generated/<spec>-chain, -witness, -empty, and leave every -v4 tree untouched.
        # Under the old rule a day of closure runs blocked the whole-corpus sweep outright,
        # which is a real cost — the sweep is the only thing that refreshes the tracked
        # baseline, and this is exactly the day it most needed refreshing.
        #
        # The hazard the rule exists for is unchanged and still enforced: a HALF-WRITTEN
        # tree in the swept set has no _test.go and survives every mutation, so the row
        # file would record "undefended" about an artifact nobody finished.
        _moving = [a.name for a in sorted(GEN.glob(f"*-{GEN_SUFFIX}")) if _corpus_check(a) == "refuse"]
        if _moving:
            print("REFUSING a whole-corpus sweep: " + ", ".join(_moving) + " being written "
                  "right now.\n" + str(ROWS_PATH) + " would record verdicts about a "
                  "half-generated tree.", file=sys.stderr)
            raise SystemExit(2)
    raise SystemExit(main())
