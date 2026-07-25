#!/usr/bin/env python3
"""How much of the fix loop's target set is BLAMED, and how much is a hypothesis?

The fix loop repairs a wider set of files than the toolchain names. `_offending_files`
returns the files the error mentions; three wideners then add root-cause candidates (the
package impl behind a persistent test failure, the package that owes a missing symbol, the
file whose purpose promises an undefined constructor), and when the error names nothing we
recognise the loop falls back to EVERY file.

Widening is right for repair — the failing test may be the file that is correct. It is
wrong for ESCALATION: moving a file to a bigger fleet member costs that model's generation
on every later round, and the live A/B found escalation is not even monotone (an escalated
member sat on a bug the base had already fixed). So the two decisions need different sets.

This measures the gap on real data: every archived failure in generated/ is run through the
CURRENT deterministic gate chain to a fixpoint (what the loop does before choosing targets),
and the residual error is fed through the loop's own target computation. It reports, per
artifact, how many files a fix round would repair and how many of those the toolchain
actually blamed. The difference is the escalation surface the old rule struck and the new
rule does not.

Read-only with respect to generated/ (every artifact is copied first). Needs the Go
toolchain; no model server, so it is free.

    python _escalation_surface.py [--limit N]

It is SLOW and looks stalled on some artifacts, which is real work, not a hang: the gate
fixpoint runs the toolchain up to ten times per artifact, and the archive contains projects
whose generated tests deadlock, so each of those checks burns the full `go test -timeout
60s`. Run it unbuffered to a file (`python -u ... > out`) rather than through a pipe, or
the progress rows sit in the pipe buffer and it looks like nothing is happening at all.

CAVEATS, because this is a surface measurement and not a fleet A/B:
  - The archives come from UNROUTED runs, so these are the strikes the old rule WOULD have
    dealt, not escalations that were observed. The observed number is in guild-code
    RESULT-fleet-ab.txt (12 escalations on a 7-file project).
  - Specs are not archived with the artifacts, so `_widen_promised_symbol_targets` (which
    needs file purposes) contributes nothing here. Every number below is therefore a LOWER
    bound on the widening.
  - Runtime widening only fires once a package has failed at runtime twice, so the dirs of
    failing test files are pre-seeded with one round: escalation needs two strikes anyway,
    so the regime where it can happen at all is the one where the loop is already stuck.
"""

from __future__ import annotations

import argparse
import io
import contextlib
import pathlib
import shutil
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from src.builder import (  # noqa: E402
    GoToolchain,
    _dir_of,
    _fix_targets,
    _is_test_failure,
    _run_deterministic_gates,
)

GENERATED = pathlib.Path(__file__).parent / "generated"


def module_of(d: pathlib.Path) -> str | None:
    gomod = d / "go.mod"
    if not gomod.exists():
        return None
    for line in gomod.read_text().splitlines():
        if line.startswith("module "):
            return line.split(None, 1)[1].strip()
    return None


def targets_of(written: dict[str, str], output: str, module: str | None) -> tuple[list[str], list[str]]:
    """The fix loop's OWN target selection (_fix_targets), not a copy of it — a
    re-implementation here would drift and quietly measure a set the builder never uses."""
    # Pre-seed the runtime widener so a persistent test failure widens (see module docstring).
    runtime_rounds = {_dir_of(p): 1 for p in written if p.endswith("_test.go")}
    with contextlib.redirect_stderr(io.StringIO()):   # the wideners log; keep the report clean
        targets, blamed = _fix_targets(written, output, runtime_rounds, [])
    # go.mod is restored deterministically and never handed to the model.
    if module:
        targets = [t for t in targets if t != "go.mod"]
    blamed = [b for b in blamed if b in targets]
    return targets, blamed


def measure(d: pathlib.Path, tc: GoToolchain, budget: float) -> dict | None:
    module = module_of(d)
    if module is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp) / d.name
        shutil.copytree(d, work)
        for junk in work.rglob("*"):          # drop stray compiled binaries
            if junk.is_file() and junk.suffix == "" and junk.stat().st_mode & 0o111:
                junk.unlink()

        # Run the gate chain to a fixpoint exactly as the fix loop does, so what we
        # measure is the residual the MODEL is asked about, not what gates already fix.
        #
        # The check is carried across iterations rather than repeated: a full check is
        # build+vet+test, and the archive contains projects whose generated tests deadlock,
        # so each one costs the whole `go test -timeout 60s`. Re-checking a tree the gates
        # did not touch buys nothing and was the single largest cost here.
        started = time.monotonic()
        ok, output = tc.check(work)
        partial = False
        for _ in range(8):
            if time.monotonic() - started > budget:
                partial = True   # reported, never silently dropped
                break
            written = {str(p.relative_to(work)): p.read_text() for p in work.rglob("*.go")}
            with contextlib.redirect_stderr(io.StringIO()):
                changed = _run_deterministic_gates(written, output, module)
            if not changed:
                break
            for path, content in changed.items():
                (work / path).write_text(content)
            ok, output = tc.check(work)

        if ok:
            return {"name": d.name, "status": "green-by-gates", "partial": partial}
        written = {str(p.relative_to(work)): p.read_text() for p in work.rglob("*.go")}
        written["go.mod"] = (work / "go.mod").read_text()
        targets, blamed = targets_of(written, output, module)
        impl = [p for p in targets if p.endswith(".go") and not p.endswith("_test.go")]
        return {
            "name": d.name,
            "status": "test" if _is_test_failure(output) else "compile",
            "files": len(written),
            "targets": len(targets),
            "blamed": len(blamed),
            "unattributed": not blamed,
            # Can escalation reach the implementation at all? A runtime failure names the
            # TEST, so an implementation defect enters the fix targets only by widening —
            # and a rule that escalates only blamed files can then never hand it to a
            # stronger model, however many rounds it spends. This counts the artifacts
            # where that hole is open: implementation files are being repaired and not one
            # of them is blamed.
            "impl_repaired": len(impl),
            "impl_blamed": len([p for p in impl if p in blamed]),
            # The gate chain had not gone quiet when the budget ran out, so this row's
            # error surface is less gate-repaired than the fix loop's would be. Kept in
            # the table (it is still a real target split) but counted separately.
            "partial": partial,
            "secs": round(time.monotonic() - started),
        }


GO_MOD_FIXTURE = "module example.com/demo\n\ngo 1.23\n"


def self_test() -> int:
    """Prove the measurement can still SEE a widened target set — no toolchain needed.

    The dangerous failure here is silent and looks like good news. `targets_of` seeds the
    runtime widener's per-directory counter so a persistent test failure widens; if that
    seeding breaks, no widening fires, every artifact reports blamed == repaired, and the
    tool concludes there was never a surface to remove. A checker whose null result is
    indistinguishable from "all clear" has to be shown firing on a planted case — the same
    reason verify_bench and check_contamination carry self-tests in guild-code.
    """
    written = {
        "go.mod": GO_MOD_FIXTURE,
        "store.go": "package store\n\nfunc Add(a, b int) int { return a + b }\n",
        "store_test.go": "package store\n\nimport \"testing\"\n\nfunc TestAdd(t *testing.T) {}\n",
    }
    failures = []

    # 1. A persistent runtime failure must widen to the impl, and the impl must NOT be blamed.
    out = "--- FAIL: TestAdd (0.00s)\n    store_test.go:4: got 3 want 4\nFAIL\n"
    targets, blamed = targets_of(written, out, "example.com/demo")
    if blamed != ["store_test.go"]:
        failures.append(f"runtime failure: expected only the test blamed, got {blamed}")
    if "store.go" not in targets:
        failures.append("runtime failure: the impl was NOT widened in — seeding is broken, "
                        "so every artifact would report zero surface")

    # 2. An error naming nothing known blames nothing but still repairs everything.
    targets, blamed = targets_of(written, "go: some toolchain complaint\n", "example.com/demo")
    if blamed:
        failures.append(f"unattributed error: expected no blame, got {blamed}")
    if set(targets) != {"store.go", "store_test.go"}:
        failures.append(f"unattributed error: expected all non-go.mod files, got {targets}")

    # 3. go.mod is restored deterministically and must never be counted as repairable.
    targets, _ = targets_of(written, "./go.mod:1:1: bad module line\n", "example.com/demo")
    if "go.mod" in targets:
        failures.append("go.mod leaked into the repaired set")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("OK — the widening is visible, unattributed errors blame nothing, go.mod is excluded")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--budget-secs", type=float, default=150.0,
                    help="per-artifact cap on the gate fixpoint; rows that hit it are "
                         "marked PARTIAL and counted separately, never dropped silently")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the measurement fires, without go or generated/")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    dirs = sorted(p for p in GENERATED.glob("_fail-*") if p.is_dir())
    if args.limit:
        dirs = dirs[: args.limit]
    tc = GoToolchain()

    rows = []
    for d in dirs:
        r = measure(d, tc, args.budget_secs)
        if r is None:
            continue
        rows.append(r)
        mark = " PARTIAL" if r.get("partial") else ""
        if r["status"] == "green-by-gates":
            print(f"{r['name']:<40} green-by-gates{mark}")
        else:
            print(f"{r['name']:<40} {r['status']:<8} files={r['files']:<3} "
                  f"repaired={r['targets']:<3} blamed={r['blamed']:<3} "
                  f"{r['secs']:>4}s {'UNATTRIBUTED' if r['unattributed'] else ''}{mark}")

    live = [r for r in rows if r["status"] != "green-by-gates"]
    if not live:
        print("\nno failing artifacts left — the gate chain clears them all")
        return 0
    tgt = sum(r["targets"] for r in live)
    bl = sum(r["blamed"] for r in live)
    wider = [r for r in live if r["targets"] > r["blamed"]]
    unattr = [r for r in live if r["unattributed"]]
    print(f"\n{len(rows)} artifacts, {len(live)} still failing after the gate chain")
    print(f"  files a fix round REPAIRS : {tgt}")
    print(f"  files the toolchain BLAMES: {bl}")
    print(f"  escalation surface removed: {tgt - bl} ({(tgt - bl) / tgt:.0%} of repaired files)")
    print(f"  artifacts where the sets differ: {len(wider)}/{len(live)}")
    print(f"  artifacts with an UNATTRIBUTED error (old rule struck every file, "
          f"new rule strikes none): {len(unattr)}/{len(live)}")

    # The structural question, not the cost question: where blame can never reach.
    unreachable = [r for r in live if r["impl_repaired"] and not r["impl_blamed"]]
    by_kind = {}
    for r in live:
        hit, tot = by_kind.get(r["status"], (0, 0))
        by_kind[r["status"]] = (hit + (1 if r in unreachable else 0), tot + 1)
    print(f"  artifacts where NO implementation file is blamed while implementation files "
          f"ARE being repaired: {len(unreachable)}/{len(live)}")
    print("      (in these, a blamed-only escalation rule can never hand an implementation "
          "defect to a stronger model)")
    for kind, (hit, tot) in sorted(by_kind.items()):
        print(f"      {kind:<8} {hit}/{tot}")
    partial = [r for r in rows if r.get("partial")]
    if partial:
        # No silent caps: a bounded run that does not say what it bounded reads as
        # full coverage.
        print(f"  PARTIAL rows (gate fixpoint hit the {args.budget_secs:.0f}s budget, so "
              f"their surface is less gate-repaired than the loop's): {len(partial)}")
        for r in partial:
            print(f"      {r['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
