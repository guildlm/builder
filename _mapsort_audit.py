"""Which functions return a slice built from a MAP without sorting it?

Go randomises map iteration per run, so such a function returns a different order every
time. When a spec promises "sorted by ID" that is a defect, and it is one a single test run
catches only by luck: the fix loop shipped a tasks-api build with rc=0 whose List() did
exactly this, and re-running its suite gave 9 pass / 3 fail over 12.

The loop now runs `go test -count=4`, which catches ~68% of a 50/50 flake. This finds the
same defect DETERMINISTICALLY, by reading the code instead of sampling its behaviour.

WHY THIS IS AN INSTRUMENT AND NOT A REPAIRING GATE
  Measured across the 25 archived artifacts plus the flaky one: 13 functions range a map
  into a returned slice, 12 sort, 1 does not — the known bug, with ZERO false positives. So
  a gate is FEASIBLE. It is still not built, because a gate REPAIRS, and repairing means
  inserting `sort.Slice` on a key this tool would have to guess. Sorting by .ID is the
  obvious choice and obvious is not the same as correct: a spec can legitimately want
  insertion order. Detecting is safe, guessing intent is not.

  The first version of this measurement said 2 unsorted and was wrong. Its pattern matched
  `for _, p := range t.Postings` — a SLICE — and reported ledger's CreateTransaction. The
  ranged field must be DECLARED map[...] in the package, or one real hit arrives beside one
  false positive, which is not a signal.

    python _mapsort_audit.py [artifact-dir ...]   # defaults to the whole archive
    python _mapsort_audit.py --self-test
"""
import pathlib, re, sys

FUNC = re.compile(r"^func\s+(\([^)]*\)\s*)?(\w+)\s*\(", re.M)
RANGE = re.compile(r"for\s+_,\s*\w+\s*:=\s*range\s+\w+\.(\w+)\b")


def funcs(text):
    hits = list(FUNC.finditer(text))
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        yield m.group(2), text[m.start():end]


def unsorted_map_returns(body: str, package_text: str) -> bool:
    """True when `body` ranges a MAP field, appends, returns, and never sorts."""
    m = RANGE.search(body)
    if not m or "append(" not in body or "return" not in body:
        return False
    if not re.search(rf"\b{m.group(1)}\s+map\[", package_text):
        return False
    return "sort." not in body


def self_test():
    pkg = "type S struct {\n\titems map[int]Task\n\tlog []Entry\n}\n"
    bad = ("func (s *S) List() []Task {\n\tvar out []Task\n"
           "\tfor _, t := range s.items {\n\t\tout = append(out, t)\n\t}\n\treturn out\n}\n")
    good = bad.replace("\treturn out", "\tsort.Slice(out, nil)\n\treturn out")
    slice_range = ("func (s *S) Sum() int {\n\tvar out []int\n"
                   "\tfor _, e := range s.log {\n\t\tout = append(out, e.N)\n\t}\n\treturn out\n}\n")
    assert unsorted_map_returns(bad, pkg), "an unsorted map return was not flagged"
    assert not unsorted_map_returns(good, pkg), "a sorted map return was flagged"
    # the false positive that made the first measurement wrong: ranging a SLICE field
    assert not unsorted_map_returns(slice_range, pkg), "ranging a slice field was flagged"
    print("OK — unsorted map return flagged, sorted one is not, and ranging a SLICE is not")


if "--self-test" in sys.argv:
    self_test(); raise SystemExit

targets = [a for a in sys.argv[1:] if not a.startswith("-")]
if targets:
    trees = []
    for t in targets:
        d = pathlib.Path(t)
        if not d.is_dir():
            raise SystemExit(f"{t} is not a directory")
        trees.append(d)
else:
    gen = pathlib.Path("generated")
    if not gen.is_dir():
        raise SystemExit("no generated/ corpus here — pass artifact directories")
    trees = sorted(gen.glob("*-v4"))

total = flagged = 0
rows = []
for art in trees:
    for f in sorted(art.rglob("*.go")):
        if f.name.endswith("_test.go"):
            continue
        text = f.read_text(errors="ignore")
        pkg = "".join(g.read_text(errors="ignore") for g in f.parent.glob("*.go")
                      if not g.name.endswith("_test.go"))
        for name, body in funcs(text):
            m = RANGE.search(body)
            if not m or "append(" not in body or "return" not in body:
                continue
            if not re.search(rf"\b{m.group(1)}\s+map\[", pkg):
                continue
            total += 1
            if "sort." not in body:
                flagged += 1
                rows.append((art.name, f.name, name))

print(f"{total} function(s) return a slice built from a map · {flagged} do NOT sort it")
for a, f, n in rows:
    print(f"  UNSORTED  {a:<24} {f:<18} {n}")
if total == 0:
    print("  (nothing to audit — no function here builds a slice from a map)")
raise SystemExit(1 if flagged else 0)
