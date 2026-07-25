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

NAMED = re.compile(r"\b(Test[A-Z][A-Za-z0-9_]*):")
WRITTEN = re.compile(r"^func (Test[A-Z][A-Za-z0-9_]*)\s*\(", re.M)


def named_in_spec(text: str) -> set[str]:
    return set(NAMED.findall(text))


def written_in_tree(tree: pathlib.Path) -> set[str]:
    out = set()
    for f in tree.rglob("*_test.go"):
        out |= set(WRITTEN.findall(f.read_text(errors="ignore")))
    return out


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

if len(trees) < 2:
    raise SystemExit("give at least TWO trees — durability cannot be measured from one, "
                     "and reading one tree twice is the mistake this exists to prevent")

named = named_in_spec(spec_path.read_text())
always, sometimes, never = report(named, trees)

# Drop from `sometimes` any test whose spec entry is NEWER than the trees that lack it.
tree_times = {name: tree_time(pathlib.Path(a)) for name, a in zip([t[0] for t in trees], args[1:])}
too_new = {}
for t in list(sometimes):
    added = entered_spec(spec_path, t)
    if added is None:
        continue
    eligible = [n for n, tt in tree_times.items() if tt >= added]
    if len(eligible) < 2:
        too_new[t] = len(eligible)
        del sometimes[t]
print(f"{args[0]}: {len(named)} named in spec, {len(trees)} tree(s)\n")
print(f"  written EVERY run : {len(always)}")
print(f"  written SOMETIMES : {len(sometimes)}   <- a closure on one of these is not durable")
print(f"  written NEVER     : {len(never)}")
for t, hits in sorted(sometimes.items()):
    print(f"      {t:<34} only in: {', '.join(hits)}")
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
