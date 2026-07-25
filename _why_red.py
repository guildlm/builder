"""Triage a RED artifact: which tests fail, do they share a SHAPE, and is the spec silent?

Written after two specs sat written off as "the coder cannot do this" for days and both
came apart in minutes the moment their suites were actually read:

    taskflow    ONE failing test, and the test was confused — it decoded the POST
                recorders as JSON arrays. The implementation was fine.
    tasks-api   SIX failing tests, ONE cause — the store started IDs at 0, so every
                lookup of id 1 returned 404. Only one of the six rows said so; the other
                five looked like routing bugs.

Neither needed a model to find. Both needed someone to run `go test` and group the output,
which is what this does, so that step stops depending on remembering to take it.

This is TRIAGE, NOT ROOT CAUSE. It reports what failed, how many distinct failure shapes
there are, and which terms the spec never mentions. Deciding what that means is still the
reader's job — the tasks-api diagnosis needed one more step (reading Update's ID-0 guard)
that no grouping would have produced.

    python _why_red.py <artifact-dir> [--spec=<name>]
    python _why_red.py --self-test
"""
import pathlib, re, subprocess, sys

FAIL_RX = re.compile(r"^\s*--- FAIL: (\w+)", re.M)


def shape(msg: str) -> str:
    """Normalise a failure message so two instances of one bug collapse together."""
    s = re.sub(r"\b\d+\b", "N", msg)
    s = re.sub(r"'[^']*'|\"[^\"]*\"|`[^`]*`", "S", s)
    # Case-folded: the tasks-api control split "Expected N, got N" from "expected N, got
    # N" and reported 5 shapes for what is one bug. Go test messages are written by
    # whoever wrote the test, so capitalisation carries no information here.
    return re.sub(r"\s+", " ", s).strip().lower()


def parse(output: str) -> list[tuple[str, list[str]]]:
    """(test name, its message lines) for every FAIL, in order."""
    out, current = [], None
    for line in output.splitlines():
        m = FAIL_RX.match(line)
        if m:
            current = (m.group(1), [])
            out.append(current)
        elif current is not None and re.match(r"^\s+\S+\.go:\d+:", line):
            current[1].append(line.split(":", 2)[-1].strip())
        elif line.startswith(("FAIL", "ok ", "---")) and not FAIL_RX.match(line):
            current = None
    return out


def self_test():
    sample = """--- FAIL: TestA (0.00s)
    handlers_test.go:47: expected 200, got 404
--- FAIL: TestB (0.00s)
    handlers_test.go:113: expected 204, got 404
--- FAIL: TestC (0.00s)
    store_test.go:82: Expected first task ID 1, title 'b', got ID 0, title b
FAIL"""
    got = parse(sample)
    assert [n for n, _ in got] == ["TestA", "TestB", "TestC"], got
    assert got[0][1] == ["expected 200, got 404"], got[0]
    # the two 404s must collapse to ONE shape; the ID row must stay its own
    shapes = {shape(m) for _, msgs in got for m in msgs}
    assert len(shapes) == 2, shapes
    assert shape("expected 200, got 404") == shape("expected 204, got 404")
    assert shape("Expected first task ID 1, title 'b', got ID 0, title b") not in {
        shape("expected 200, got 404")}
    # a green run must produce nothing rather than an empty-looking success
    assert parse("ok  \tguildlm.dev/x\t0.2s") == []
    print("OK — failures parsed, two 404s collapse to one shape, a distinct row stays distinct")


if "--self-test" in sys.argv:
    self_test(); raise SystemExit

if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
    raise SystemExit(__doc__)
art = pathlib.Path(sys.argv[1])
if not art.is_dir():
    raise SystemExit(f"{art} is not a directory")

proc = subprocess.run(["go", "test", "./..."], cwd=art, capture_output=True, text=True,
                      timeout=300)
fails = parse(proc.stdout + proc.stderr)
if not fails:
    # Distinguish "nothing failed" from "nothing ran" — but PER PACKAGE, because the
    # first version of this check asked whether the phrase "no test files" appeared
    # ANYWHERE and then declared that nothing ran. Swept across the archive it called
    # four healthy multi-package projects untested: ledger, taskapi, taskapipro and
    # workapi all have 6-8 test files, and only their cmd/server package has none, which
    # is correct for a main. I shipped the same conflation I spent today hunting — "some
    # of it did not run" reported as "none of it ran" — and the corpus sweep is what
    # caught it, not the two artifacts it was built against.
    tested = len(re.findall(r"^ok\s+\S+", proc.stdout, re.M))
    untested = len(re.findall(r"^\?\s+\S+\s+\[no test files\]", proc.stdout, re.M))
    if tested:
        note = f"suite is green — {tested} package(s) ran tests"
        if untested:
            note += f", {untested} had none"
    else:
        note = f"NO PACKAGE RAN A TEST ({untested} with no test files)"
    print(f"no failing tests ({note})")
    raise SystemExit(0 if tested else 1)

groups: dict[str, list[str]] = {}
for name, msgs in fails:
    for m in msgs:
        groups.setdefault(shape(m), []).append(name)

print(f"{len(fails)} failing test(s), {len(groups)} distinct failure shape(s)\n")
for sh, names in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    uniq = sorted(set(names))
    print(f"  x{len(names):<3} {sh[:72]}")
    print(f"       in: {', '.join(uniq)}")
if len(groups) == 1 and len(fails) > 1:
    print(f"\n  ALL {len(fails)} failures share one shape — look for ONE cause, not {len(fails)}.")

# The spec-silence heuristic that used to live here is DELETED, not disabled.
#
# It grepped the failure text for words the spec never used, on the theory that
# tasks-api's real defect — a spec that never said where the ID sequence STARTS — would
# surface that way. Run against the two cases whose answers I already knew, it returned
# "second" for tasks-api and "expected" for taskflow: noise words from the assertion
# prose, not the silence. It found neither real cause.
#
# Deleted rather than kept behind a flag, for the same reason the corrective-density
# metric was deleted this afternoon: a failed heuristic left in the file is how it gets
# re-run later by someone who does not know it failed its controls, and a plausible-looking
# word list is exactly the kind of output that gets believed.
#
# What survives is the part that DID earn its keep: how many tests fail, and whether they
# cluster. That alone is what would have saved days here — taskflow's suite had exactly
# ONE failing test the whole time it was written off as a capability wall.
