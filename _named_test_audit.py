#!/usr/bin/env python3
"""Which tests does a spec NAME, and which of those did the model not write?

This audit exists because of a loss that the project's own metric could not see.
taskapipro's spec names TestListSorted (line 140). A spec edit of mine — in a
DIFFERENT file's section — deleted it from the generated store test, 2/2,
deterministically. The run came back GREEN with coverage UP, 82.9 -> 83.5, and
every gate passed. Nothing reported it. _test_rule's own ledger already knew why:
the workapi finding is "invisible to coverage: sorted and unsorted code execute
the same lines". A test that is never written cannot lower a coverage number that
the code under it already earns some other way.

So green + coverage cannot answer "did we build what the spec asked for". Only
the artifact can, and only against the spec's own words. That is this script.

METHOD, and its limits, stated rather than implied:
  - A spec NAMES a test when its file purposes mention `TestSomething`. That is
    the spec-writer's contract with the model; this project's law is that
    implicit means broken and naming is the spec-writer's job.
  - A named test COUNTS AS PRESENT if its name appears as a WHOLE IDENTIFIER in
    the project's *_test.go files — not merely as `func TestX`. A model may
    legitimately fold a named case into a subtest (`t.Run("TestX", ...)`), and
    calling that a miss would be my grep confirming what I want rather than what
    is true.
  - WHOLE IDENTIFIER, not substring, and that distinction is not pedantry: the
    first version of this file matched substrings, so TestCreateAccountDuplicate
    read as PRESENT purely because TestCreateAccountDuplicateIsErrExists contains
    it — and TestList could NEVER have been reported missing while TestListLimit
    existed. That is a FALSE NEGATIVE in the direction of "nothing is wrong",
    which is the direction this project's greps keep failing in. (Today alone:
    a guard-drop story died because the grep matched a substring INSIDE the
    correct guard.) An auditor that cannot report a miss is decoration.
  - RENAMED is its own class, reported separately: no exact match, but some test
    function's name STARTS with the spec's name (TestGetAccountMissing ->
    TestGetAccountMissingIsErrNotFound). The scenario is almost certainly there
    under a longer name. That is a naming drift, not a hole, and calling it a
    hole would be cheating in the opposite direction.
  - MISSING therefore means: the spec said the name, and no test file contains it
    as a whole identifier, and no test function extends it. That is a real gap.
  - This measures the MODEL's output against the SPEC's words. It does not
    measure whether the test is any good. A named test that is present but
    vacuous is out of scope here and needs the artifact read.

Usage: _named_test_audit.py [spec ...]     (default: every spec with an artifact)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
SPECS = ROOT / "specs"
GEN = ROOT / "generated"

# A test name as a spec writer writes it: Test + CamelCase. Anchored to a word
# boundary so `TestListSorted` inside prose still counts — the spec naming it in
# a sentence IS the spec naming it.
NAME_RE = re.compile(r"\bTest[A-Z][A-Za-z0-9_]*")


def spec_named_tests(spec_path: Path) -> set[str]:
    """Every test name the spec utters, across all file purposes."""
    doc = yaml.safe_load(spec_path.read_text())
    names: set[str] = set()
    for f in doc.get("files", []):
        names.update(NAME_RE.findall(f.get("purpose", "") or ""))
    return names


def artifact_test_text(art: Path) -> tuple[str, set[str]]:
    """All test-file text, and the set of top-level `func TestX` names."""
    blob: list[str] = []
    funcs: set[str] = set()
    for p in art.rglob("*_test.go"):
        text = p.read_text(errors="replace")
        blob.append(text)
        funcs.update(re.findall(r"^func (Test[A-Za-z0-9_]+)", text, re.M))
    return "\n".join(blob), funcs


def audit(spec: str) -> dict | None:
    spec_path = SPECS / f"{spec}.yaml"
    art = GEN / f"{spec}-v4"
    if not spec_path.exists() or not art.is_dir():
        return None
    # An artifact is only evidence once it is FINISHED. A run in flight has
    # written some of its files and not the rest, so every unwritten test looks
    # exactly like a test the model refused to write. The first run of this
    # script reported taskapipro as 44 tests missing while a probe was actively
    # rewriting taskapipro-v4 — a fabricated catastrophe that would have sent me
    # hunting a bug that did not exist. Compare against what the spec DECLARES:
    # short by any file means mid-run, and mid-run means say so, not score it.
    # AND ONLY EVIDENCE ABOUT THE SPEC IT WAS BUILT FROM. This compares a LIVE spec
    # against a FROZEN artifact, so the moment a spec names a new test the audit reports it
    # MISSING — not because the coder refused to write it, but because the archive predates
    # the sentence. Today that showed up as shortener "missing" the exact three tests I had
    # just closed and watched pass in fresh runs. Same shape as the mid-run case above: a
    # real-looking failure manufactured by comparing across time. Flag it, do not score it.
    # LIMITATION, demonstrated rather than assumed: mtime is the only cheap signal here
    # and it is forgeable. The over-fire check for this flag was `touch`ing an
    # artifact's .go files, and that alone made a genuinely stale artifact report as
    # fresh — as a checkout, a copy or a rsync would too. So the flag is a HINT THAT
    # CAN MISS, never a proof of freshness: its absence means nothing, its presence is
    # worth heeding. (jsonapi-v4's mtimes were touched by that very check, so its flag
    # is unreliable until it is regenerated.)
    stale = spec_path.stat().st_mtime > max((p.stat().st_mtime for p in art.rglob("*.go")),
                                            default=0)
    declared = {f["path"] for f in yaml.safe_load(spec_path.read_text())
                .get("files", []) if f.get("path", "").endswith(".go")}
    present = {str(p.relative_to(art)) for p in art.rglob("*.go")}
    if declared - present:
        return {"spec": spec, "incomplete": sorted(declared - present)}
    named = spec_named_tests(spec_path)
    if not named:
        return {"spec": spec, "named": 0, "missing": [], "subtest_only": [],
                "renamed": [], "funcs": 0}
    blob, funcs = artifact_test_text(art)
    return {"spec": spec, "named": len(named), "funcs": len(funcs), "stale": stale,
            **classify(named, blob, funcs)}


def classify(named: set[str], blob: str, funcs: set[str]) -> dict:
    """Sort each spec-named test into missing / renamed / subtest_only.

    Pure — the three inputs are all it needs — so --self-test can hold it to the exact
    distinctions the METHOD notes above argue for, instead of them being prose."""

    def whole(name: str) -> bool:
        """Present as a complete identifier — `TestList` does not match inside
        `TestListLimit`. (?!\\w) is the whole point of this function."""
        return re.search(rf"\b{re.escape(name)}(?!\w)", blob) is not None

    missing, renamed, subtest_only = [], [], []
    for n in sorted(named):
        if whole(n):
            if n not in funcs:
                # Named, not a top-level func, but there as a whole identifier:
                # folded into a subtest or a helper. Present — worth seeing,
                # because it is the difference between obeying the name and
                # merely echoing it.
                subtest_only.append(n)
            continue
        ext = sorted(f for f in funcs if f.startswith(n))
        if ext:
            renamed.append(f"{n} -> {ext[0]}")
        else:
            missing.append(n)
    return {"missing": missing, "subtest_only": subtest_only, "renamed": renamed}


MIRROR_RE = re.compile(r"the same (?:\w+ )?(?:four|three|two|set|methods)? ?for (\w+)"
                       r"|mirroring the (\w+)", re.I)


def mirror_gap(spec_text: str) -> tuple[str, int, int] | None:
    """A spec that mirrors an implementation BY REFERENCE but not its tests BY NAME.

    Measured, not guessed. taskflow says "the same four for Project" and names 13 tests on
    the tasks side and 6 on projects; three of the corpus's undefended promises are on that
    projects route, found by three different mutation shapes. taskapi uses the SAME phrase
    and names 19 and 17 — and has none of them (logs/FINDING-mirrored-routes.txt).

    So the idiom is fine and the asymmetry is the defect: the model implements everything
    it is told to implement and tests everything it is told to test, and a spec that
    mirrors one and not the other doubles the code while holding coverage still.

    Returns (mirrored_entity, primary_named, mirror_named) when the mirror side has fewer
    than half the primary's named tests, else None.
    """
    m = MIRROR_RE.search(spec_text)
    if not m:
        return None
    entity = m.group(1) or m.group(2)
    named = set(re.findall(r"\bTest[A-Za-z]+", spec_text))
    mirror = {n for n in named if entity.lower() in n.lower()}
    primary = named - mirror
    if not primary or len(mirror) * 2 >= len(primary):
        return None
    return entity, len(primary), len(mirror)


def self_test() -> int:
    """Hold the classifier to the four distinctions its METHOD notes argue for.

    The one that matters most is the substring trap, because this file has already been
    wrong in that exact direction: the first version matched substrings, so TestList could
    never be reported missing while TestListLimit existed — a false negative pointing at
    "nothing is wrong", which is the direction an auditor must never fail in.
    """
    cases = [
        ("a whole-identifier match is PRESENT, not missing",
         {"TestAdd"}, "func TestAdd(t *testing.T) {}", {"TestAdd"},
         {"missing": [], "renamed": [], "subtest_only": []}),
        ("a substring match must NOT count as present",
         {"TestList"}, "func TestListLimit(t *testing.T) {}", {"TestListLimit"},
         {"missing": [], "renamed": ["TestList -> TestListLimit"], "subtest_only": []}),
        ("genuinely absent is MISSING",
         {"TestGone"}, "func TestSomethingElse(t *testing.T) {}", {"TestSomethingElse"},
         {"missing": ["TestGone"], "renamed": [], "subtest_only": []}),
        ("folded into a subtest is PRESENT, and reported as such",
         {"TestNested"}, 'func TestOuter(t *testing.T) { t.Run("TestNested", nil) }',
         {"TestOuter"},
         {"missing": [], "renamed": [], "subtest_only": ["TestNested"]}),
    ]
    failures = []
    for label, named, blob, funcs, want in cases:
        got = classify(named, blob, funcs)
        for k, v in want.items():
            if got[k] != v:
                failures.append(f"[{label}] {k}: got {got[k]}, want {v}")
    # The mirror check, held to the two real specs that isolate it: taskflow mirrors the
    # code and not the tests and must flag; taskapi mirrors both and must not. A detector
    # with only a positive case cannot be told from one that flags everything.
    here = Path(__file__).parent
    tf, ta = here / "specs/taskflow.yaml", here / "specs/taskapi.yaml"
    if tf.exists() and ta.exists():
        if mirror_gap(tf.read_text()) is None:
            failures.append("taskflow mirrors code but not tests (13 vs 6) and was NOT flagged")
        if mirror_gap(ta.read_text()) is not None:
            failures.append("taskapi mirrors BOTH (19 vs 17) and was flagged anyway")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("OK — whole identifiers count, substrings do not, absent is MISSING, "
          "a subtest is present, and the mirror check separates taskflow from taskapi")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    wanted = [a for a in sys.argv[1:] if not a.startswith('-')]
    explicit = bool(wanted)
    if not wanted:
        wanted = sorted(p.stem for p in SPECS.glob("*.yaml")
                        if (GEN / f"{p.stem}-v4").is_dir())
    rows = [r for r in (audit(s) for s in wanted) if r]
    # An UNMATCHED NAME MUST NOT READ AS "CLEAN". Asked about a spec that does not exist,
    # this printed the header, no rows, and exited 0 — indistinguishable from "audited it,
    # nothing missing". Found by probing every instrument with a target that does not
    # exist, after the same shape nearly cost a result in _hole_closed.
    if explicit and not rows:
        raise SystemExit(f"none of {', '.join(wanted)} matched a spec with a -v4 artifact; "
                         f"an empty report is not the same as a clean one")
    skipped = [r for r in rows if r.get("incomplete")]
    rows = [r for r in rows if not r.get("incomplete")]
    total_named = total_missing = 0
    print(f"{'spec':<24} {'named':>5} {'miss':>5} {'funcs':>5}  missing")
    print("-" * 78)
    for r in sorted(rows, key=lambda r: -len(r["missing"])):
        total_named += r["named"]
        total_missing += len(r["missing"])
        miss = ", ".join(r["missing"][:4])
        if r.get("stale") and r["missing"]:
            miss += "   [STALE: spec edited after this artifact was generated]"
        if len(r["missing"]) > 4:
            miss += f", +{len(r['missing']) - 4} more"
        print(f"{r['spec']:<24} {r['named']:>5} {len(r['missing']):>5} "
              f"{r['funcs']:>5}  {miss}")
        if r["subtest_only"]:
            print(f"{'':<24} {'':>5} {'':>5} {'':>5}  "
                  f"(subtest/helper only: {', '.join(r['subtest_only'][:4])})")
        if r["renamed"]:
            print(f"{'':<24} {'':>5} {'':>5} {'':>5}  "
                  f"(renamed, present: {'; '.join(r['renamed'][:3])})")
    print("-" * 78)
    print(f"{'TOTAL':<24} {total_named:>5} {total_missing:>5}")
    for r in skipped:
        print(f"\n!! {r['spec']}: SKIPPED — artifact INCOMPLETE, "
              f"{len(r['incomplete'])} declared file(s) not written "
              f"(e.g. {r['incomplete'][0]}).\n"
              f"   A run is probably in flight. Scoring it would invent "
              f"missing tests. Re-run when it lands.")
    print()
    print("MISSING = the spec said the name; no test file contains it. Coverage "
          "cannot see these:\na test never written lowers no number. Measured on "
          "ledger 2026-07-17: deleting\nevery credit from the apply loop keeps "
          "build+vet+the FULL suite GREEN, and the one\ntest the spec named "
          "(TestCreateTransactionMovesBalances) fails it instantly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
