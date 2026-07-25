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
import re, sys, pathlib
sys.path.insert(0, "/Users/fatihturker/Desktop/Personal/Dev/guildlm/builder")
from _teeth_suite import verdict_for, GEN

SWAP = {"StatusNotFound": "StatusBadRequest", "StatusCreated": "StatusOK",
        "StatusBadRequest": "StatusNotFound", "StatusTooManyRequests": "StatusServiceUnavailable",
        "StatusMovedPermanently": "StatusFound", "StatusNoContent": "StatusOK",
        "StatusConflict": "StatusBadRequest", "StatusMethodNotAllowed": "StatusBadRequest",
        "StatusUnprocessableEntity": "StatusBadRequest", "StatusOK": "StatusAccepted"}
CODE = re.compile(r"^\s*(?!//)(?!\s*\*).*http\.(Status[A-Za-z]+)")

# SHAPE 4: error wrapping. `fmt.Errorf("...: %w", ErrX)` -> `%v` leaves the message
# BYTE-IDENTICAL and breaks errors.Is. That is the sharpest probe in this file: a test
# that compares the error string still passes, and only a test that actually calls
# errors.Is notices. Six specs promise errors.Is behaviour by name, so when this survives
# it is a promise with a test that checks the wrong thing — not merely a missing test.
WRAP = re.compile(r'fmt\.Errorf\("([^"]*)%w([^"]*)"')


def wrap_rows():
    out = []
    for art in sorted(GEN.glob("*-v4")):
        for f in sorted(art.glob("*.go")):
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
                sentinel = re.search(r"Err[A-Za-z]*", text[text.index(orig):][:200])
                tag = f"%w -> %v ({sentinel.group(0) if sentinel else '?'})"
                v, _ = verdict_for(art, f.name, mut)
                out.append((art.name, f.name, tag, v))
                print(f"{art.name:<26} {f.name:<22} {tag:<26} {v}", flush=True)
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
    for art in sorted(GEN.glob("*-v4")):
        for f in sorted(art.glob("*.go")):
            if f.name.endswith("_test.go"):
                continue
            hit = None
            for ln in f.read_text(errors="ignore").splitlines():
                m = COMPARATOR.search(ln)
                if m:
                    hit = (f.name, m.group(0), f"{m.group(1)} > {m.group(2)}",
                           m.group(1).split(".")[-1]); break
            if not hit:
                continue
            rel, line, flipped, field = hit
            def mut(text, a=line, b=flipped):
                return text.replace(a, b, 1) if a in text else None
            v, _ = verdict_for(art, rel, mut)
            out.append((art.name, rel, f"reverse sort by {field}", v))
            print(f"{art.name:<26} {rel:<22} {('reverse sort by ' + field):<26} {v}", flush=True)
            if not ALL_SITES:
                break
    return out


# SHAPE 2: response headers. A wrong Content-Type is invisible to a test that only reads
# the body, and the campaign's own taxonomy names headers as a hole shape — kvservice and
# jsonapi both had one closed by hand. Dropping the header entirely is the sharper probe:
# changing the value can still be caught by a strict equality assert, but a test that never
# looks at headers at all cannot notice either.
HEADER = re.compile(r'^\s*w\.Header\(\)\.Set\("([^"]+)", *"[^"]*"\)')


def header_rows():
    out = []
    for art in sorted(GEN.glob("*-v4")):
        for f in sorted(art.glob("*.go")):
            if f.name.endswith("_test.go"):
                continue
            hit = None
            for ln in f.read_text(errors="ignore").splitlines():
                m = HEADER.match(ln)
                if m:
                    hit = (f.name, m.group(1), ln.strip()); break
            if not hit:
                continue
            rel, header, line = hit
            def mut(text, ln=line):
                return text.replace(ln, "// MUTANT: header dropped", 1) if ln in text else None
            v, _ = verdict_for(art, rel, mut)
            out.append((art.name, rel, f"drop {header}", v))
            print(f"{art.name:<26} {rel:<22} {('drop ' + header):<26} {v}", flush=True)
            break
    return out


# Probe every site, not just the first. The first pass stopped at one status write per
# artifact because it was the cheap sweep; shortener alone has two 400 sites and only one
# was ever probed, and the one that was probed turned out to be the real hole. Under-
# sampling in a hole hunt is the same error as a green suite: absence of a finding read as
# absence of a hole.
ALL_SITES = "--all-sites" in sys.argv

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
    print("OK — a defended status is CAUGHT, an unasserted one SURVIVES, "
          "and the benign label matches only the recorder default")
    return 0


if "--self-test" in sys.argv:
    raise SystemExit(self_test())


rows = []
for art in sorted(GEN.glob("*-v4")):
    for f in sorted(art.glob("*.go")):
        if f.name.endswith("_test.go"):
            continue
        hit = None
        for ln in f.read_text(errors="ignore").splitlines():
            m = CODE.match(ln)
            if m and m.group(1) in SWAP:
                hit = (f.name, m.group(1), ln.strip()); break
        if hit:
            rel, old, line = hit
            new = SWAP[old]
            def mut(text, o=old, n=new):
                out, k = re.subn(rf"http\.{o}\b", f"http.{n}", text, count=1)
                return out if k else None
            v, note = verdict_for(art, rel, mut)
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
            if not ALL_SITES:
                break
print("\n=== shape 2: drop a response header ===")
rows += header_rows()
print("\n=== shape 3: reverse a sort comparator ===")
rows += sort_rows()
print("\n=== shape 4: unwrap an error (%w -> %v) ===")
rows += wrap_rows()
surv = [r for r in rows if r[3] == "SURVIVED"]
star = [r for r in rows if r[3] == "SURVIVED*"]
print(f"\n{len(rows)} probes · {len(surv)} SURVIVED (green build, real behaviour change)"
      + (f" · {len(star)} SURVIVED* (known-benign: a statusRecorder default, log-only)"
         if star else ""))
for r in surv:
    print("   ", r)
print("\nA SURVIVED row is a CANDIDATE. The next question is always whether the SPEC\n"
      "promises the behaviour that was broken — on the first run one survivor was a\n"
      "genuine undefended promise and the other was log-only output.")
