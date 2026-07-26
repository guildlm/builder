"""Which spec-named tests does the model write EVERY run, and which only sometimes?

A closure is verified on the artifact that closed it. That says nothing about whether the
next run writes the same test — and on the one spec re-run enough times to check, it does
not: taskflow's Content-Type assertion appeared in run 1 and in neither of runs 2 and 3,
so a hole recorded as closed was open again twice.

Every other closure today was graded on a spec with exactly ONE tree, where re-checking
"the latest artifact" re-checks the artifact it was graded on. That is not durability
evidence, it is the same measurement read twice. This makes the real check cheap enough
to run.

    python _test_durability.py <spec-name> <tree> <tree> [tree ...]
    python _test_durability.py --self-test
"""
import pathlib, re, sys

# ONE EXTRACTOR, shared with _named_test_audit. This file had its own regex requiring a
# COLON after the test name, and six specs name tests with an em dash instead —
# `TestListSorted — POST users id "2" then "1"`. It silently measured 1 of usersapi's 3
# named tests, 8 of shortener's 11, 19 of workapi's 31, and I published "0 intermittent"
# for several of them without noticing the denominator was wrong. Two extractors that
# disagree is one extractor too many.
_NTA = None


def _nta():
    """_named_test_audit, imported once. It owns BOTH extractors."""
    global _NTA
    if _NTA is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("nta", "_named_test_audit.py")
        mod = importlib.util.module_from_spec(spec)
        argv, sys.argv = sys.argv, ["_named_test_audit.py", "--import-only"]
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass
        finally:
            sys.argv = argv
        _NTA = mod
    return _NTA


NAMED = _nta().NAME_RE
# The Go-side reader is shared too. These two files had DIFFERENT patterns for "tests
# the artifact contains" — mine required an uppercase letter after Test and an opening
# paren, the other required neither — and they agree on all 25 archived artifacts today.
# Agreeing now is not the same as agreeing later, and the spec-side pair that disagreed
# had been silently wrong for hours. Measured first, then unified so they cannot diverge.
_WRITTEN_READER = None


def named_in_spec(text: str) -> set[str]:
    return set(NAMED.findall(text))


def written_in_tree(tree: pathlib.Path) -> set[str]:
    global _WRITTEN_READER
    if _WRITTEN_READER is None:
        _WRITTEN_READER = _nta().artifact_test_text
    return _WRITTEN_READER(tree)[1]


def entered_spec(spec_path: pathlib.Path, test: str) -> int | None:
    """Unix time of the commit that first put `test` in the spec, or None if unknown.

    Turns a printed caveat into an actual filter. A test the spec gained recently CANNOT
    appear in trees generated before it existed, and counting those trees against it
    reports a brand-new test as intermittent.
    """
    import subprocess
    try:
        out = subprocess.run(
            ["git", "log", "-S", test, "--format=%ct", "--", str(spec_path)],
            capture_output=True, text=True, timeout=30).stdout.split()
    except Exception:
        return None
    return int(out[-1]) if out else None


def tree_time(tree: pathlib.Path) -> int:
    """When the tree was generated, by its newest file.

    mtime is forgeable — a checkout or a copy resets it, as `touch` was shown to do
    earlier in this repo — so this is a best effort, not a proof. It is only used to
    EXCLUDE trees that predate a test, which is the direction that can only make the
    'sometimes' set smaller and more honest.
    """
    times = [f.stat().st_mtime for f in tree.rglob("*.go")]
    return int(max(times)) if times else 0


def report(named, per_tree):
    """(always, sometimes, never) — sometimes is the interesting set."""
    always, sometimes, never = set(), {}, set()
    for t in sorted(named):
        hits = [name for name, w in per_tree if t in w]
        if len(hits) == len(per_tree):
            always.add(t)
        elif hits:
            sometimes[t] = hits
        else:
            never.add(t)
    return always, sometimes, never


def self_test():
    named = {"TestA", "TestB", "TestC"}
    per = [("r1", {"TestA", "TestB"}), ("r2", {"TestA"}), ("r3", {"TestA", "TestB"})]
    always, sometimes, never = report(named, per)
    assert always == {"TestA"}, always
    assert set(sometimes) == {"TestB"} and sometimes["TestB"] == ["r1", "r3"], sometimes
    assert never == {"TestC"}, never
    # a single tree must not be able to report anything as durable
    a2, s2, n2 = report(named, [("r1", {"TestA"})])
    assert a2 == {"TestA"} and n2 == {"TestB", "TestC"}
    print("OK — always/sometimes/never separated, and 'sometimes' names the runs")


if "--self-test" in sys.argv:
    self_test(); raise SystemExit

args = [a for a in sys.argv[1:] if not a.startswith("-")]
if len(args) < 2:
    raise SystemExit(__doc__)
spec_path = pathlib.Path("specs") / f"{args[0]}.yaml"
if not spec_path.exists():
    raise SystemExit(f"no spec {spec_path}")
trees = []
for a in args[1:]:
    d = pathlib.Path(a)
    if not d.is_dir():
        raise SystemExit(f"{a} is not a directory")
    trees.append((d.name, written_in_tree(d)))

def assertions_in(tree: pathlib.Path) -> dict:
    """How many assertions each named test carries, per tree.

    Presence is not content. Promoting ratelimit's verified-green trees kept all five test
    functions and dropped every Retry-After and 200 assertion inside them, and this tool
    reported "0 intermittent" throughout because it only ever asked whether a NAME existed.
    A test that persists while what it checks changes is invisible to a presence check and
    is exactly what took the corpus from 15 SURVIVED to 18.
    """
    out = {}
    for f in tree.rglob("*_test.go"):
        text = f.read_text(errors="ignore")
        blocks = re.split(r"^func (Test[A-Za-z0-9_]+)", text, flags=re.M)
        for name, body in zip(blocks[1::2], blocks[2::2]):
            n = len(re.findall(r"\bt\.(?:Error|Errorf|Fatal|Fatalf)\b", body))
            # WHAT it compares, not only how often. A count alone is coarse — a test can
            # swap one assertion for another and hold steady — so collect the SUBJECTS of
            # its comparisons too: the http.StatusX constants, header names and field
            # accesses that appear in `if ... != ...` conditions. ratelimit's regression
            # was exactly a swap of subject, not a change of count.
            subjects = set()
            for cond in re.findall(r"if\s+([^{\n]+?)\s*\{", body):
                if "!=" not in cond and "==" not in cond:
                    continue
                subjects |= set(re.findall(r"http\.Status\w+|\"[A-Za-z-]+\"|\w+\.\w+", cond))
            out[name] = (n, frozenset(subjects))
    return out


if len(trees) < 2:
    raise SystemExit("give at least TWO trees — durability cannot be measured from one, "
                     "and reading one tree twice is the mistake this exists to prevent")

# Show each tree's inferred generation time. The mtime caveat MATERIALISED: today's
# non-vacuity proofs deleted and restored files inside generated/ratelimit-v4, so an
# archive weeks old carried a timestamp 20 minutes NEWER than the spec entry it predates,
# and TestContentTypeJSON was reported intermittent when it is not. Printing the times
# makes an implausible one visible instead of silently wrong.
import datetime as _dt
print("  trees, by inferred generation time (mtime — forgeable, check for surprises):")
for _n, _a in zip([t[0] for t in trees], args[1:]):
    _t = tree_time(pathlib.Path(_a))
    print(f"      {_n:<26} {_dt.datetime.fromtimestamp(_t):%Y-%m-%d %H:%M}")
print()

named = named_in_spec(spec_path.read_text())
always, sometimes, never = report(named, trees)

# Drop from `sometimes` any test whose spec entry is NEWER than the trees that lack it.
tree_times = {name: tree_time(pathlib.Path(a)) for name, a in zip([t[0] for t in trees], args[1:])}
too_new = {}
stable_among_eligible = {}
for t in list(sometimes):
    added = entered_spec(spec_path, t)
    if added is None:
        continue
    eligible = [n for n, tt in tree_times.items() if tt >= added]
    if len(eligible) < 2:
        too_new[t] = len(eligible)
        del sometimes[t]
        continue
    # RE-EVALUATE, do not just count. The first version filtered only on how MANY trees
    # were eligible and left the verdict from the all-trees pass untouched, so a test
    # present in every ELIGIBLE tree but missing from older ones was still reported
    # intermittent. shortener's TestShortenMalformedJSON is exactly that: it appears in
    # both trees generated after the spec named it, and was being called unstable.
    hits = set(sometimes[t])
    if set(eligible) <= hits:
        stable_among_eligible[t] = eligible
        del sometimes[t]
print(f"{args[0]}: {len(named)} named in spec, {len(trees)} tree(s)\n")
print(f"  written EVERY run : {len(always)}")
print(f"  written SOMETIMES : {len(sometimes)}   <- a closure on one of these is not durable")
print(f"  written NEVER     : {len(never)}")
for t, hits in sorted(sometimes.items()):
    print(f"      {t:<34} only in: {', '.join(hits)}")
# CONTENT, beside presence.
per_tree_asserts = {n: assertions_in(pathlib.Path(a)) for n, a in zip([t[0] for t in trees], args[1:])}
shifted = {}
for t in sorted(always):
    vals = {n: d.get(t, (0, frozenset())) for n, d in per_tree_asserts.items()}
    counts = {n: v[0] for n, v in vals.items()}
    subj = {n: v[1] for n, v in vals.items()}
    if len(set(counts.values())) > 1 or len(set(subj.values())) > 1:
        lost = set().union(*subj.values()) - set.intersection(*[set(v) for v in subj.values()])
        shifted[t] = (counts, sorted(lost)[:4])
if shifted:
    print(f"\n  PRESENT EVERY RUN but NOT ASSERTING THE SAME THINGS ({len(shifted)}):")
    for t, (counts, lost) in sorted(shifted.items()):
        detail = ", ".join(f"{n}:{c}" for n, c in counts.items())
        print(f"      {t:<34} {detail}")
        if lost:
            print(f"          not asserted in every run: {', '.join(lost)}")
    print("      A name persisting is not the same as a promise staying defended.")

for t, el in sorted(stable_among_eligible.items()):
    print(f"      {t:<34} stable — in ALL {len(el)} run(s) since the spec named it")
for t, n in sorted(too_new.items()):
    print(f"      {t:<34} TOO NEW to judge — {n} eligible run(s), needs 2")
if sometimes:
    # A test the spec gained RECENTLY could not appear in trees generated before it
    # existed, and this tool cannot see when a spec entry was added — so "sometimes"
    # mixes genuinely intermittent tests with newly-named ones. Same shape as the
    # live-spec-vs-frozen-artifact problem in _named_test_audit, in a new guise, and
    # worth saying out loud rather than letting the count overstate.
    print("\n  NOTE: rows above are judged only against trees generated AFTER the spec named\n"
          "  them — `git log -S` gives the entry date, tree mtime the generation date. mtime\n"
          "  is forgeable (a checkout or copy resets it), so this filter is best-effort; it\n"
          "  only ever EXCLUDES trees, which can shrink 'sometimes' but never inflate it.")
for t in sorted(never):
    print(f"      {t:<34} in NO run")
raise SystemExit(1 if (sometimes or never) else 0)
