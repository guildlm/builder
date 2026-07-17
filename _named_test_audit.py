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
  - A named test COUNTS AS PRESENT if its name appears anywhere in the project's
    *_test.go files — not merely as `func TestX`. A model may legitimately fold a
    named case into a subtest (`t.Run("TestX", ...)`), and calling that a miss
    would be my grep confirming what I want rather than what is true.
  - MISSING therefore means: the spec said the name, and the name is nowhere in
    any test file. That is a real gap, not a stylistic difference.
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
    declared = {f["path"] for f in yaml.safe_load(spec_path.read_text())
                .get("files", []) if f.get("path", "").endswith(".go")}
    present = {str(p.relative_to(art)) for p in art.rglob("*.go")}
    if declared - present:
        return {"spec": spec, "incomplete": sorted(declared - present)}
    named = spec_named_tests(spec_path)
    if not named:
        return {"spec": spec, "named": 0, "missing": [], "subtest_only": [],
                "funcs": 0}
    blob, funcs = artifact_test_text(art)
    missing = sorted(n for n in named if n not in blob)
    # Named, not a top-level func, but present in the text: folded into a
    # subtest or a helper. Present — but worth seeing, because it is the
    # difference between the model obeying the name and merely echoing it.
    subtest_only = sorted(n for n in named if n not in funcs and n not in missing)
    return {"spec": spec, "named": len(named), "missing": missing,
            "subtest_only": subtest_only, "funcs": len(funcs)}


def main() -> int:
    wanted = sys.argv[1:]
    if not wanted:
        wanted = sorted(p.stem for p in SPECS.glob("*.yaml")
                        if (GEN / f"{p.stem}-v4").is_dir())
    rows = [r for r in (audit(s) for s in wanted) if r]
    skipped = [r for r in rows if r.get("incomplete")]
    rows = [r for r in rows if not r.get("incomplete")]
    total_named = total_missing = 0
    print(f"{'spec':<24} {'named':>5} {'miss':>5} {'funcs':>5}  missing")
    print("-" * 78)
    for r in sorted(rows, key=lambda r: -len(r["missing"])):
        total_named += r["named"]
        total_missing += len(r["missing"])
        miss = ", ".join(r["missing"][:4])
        if len(r["missing"]) > 4:
            miss += f", +{len(r['missing']) - 4} more"
        print(f"{r['spec']:<24} {r['named']:>5} {len(r['missing']):>5} "
              f"{r['funcs']:>5}  {miss}")
        if r["subtest_only"]:
            print(f"{'':<24} {'':>5} {'':>5} {'':>5}  "
                  f"(subtest/helper only: {', '.join(r['subtest_only'][:4])})")
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
