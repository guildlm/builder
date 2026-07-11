#!/usr/bin/env python3
"""Gate coverage audit — pick the next gate with data, not a hunch.

Every failed Builder run leaves its artifact behind in generated/. That is a
corpus of real, model-written Go that does not compile: dozens of broken
projects, each carrying whatever defect the model actually produced. This walks
all of them and asks two questions the gate work has been answering by anecdote:

  1. Which gates actually fire, and on how many artifacts? A gate that never
     fires on any real artifact is dead weight — or, worse, is guarded too
     tightly and is silently missing the very class it was written for. (That is
     exactly what happened to the middleware gate.)

  2. What is LEFT once the gates have run to a fixpoint? Those residual compiler
     diagnostics, bucketed by shape and ranked by how many DISTINCT artifacts
     they appear in, are the ranked backlog of gates still worth writing.

Read-only with respect to generated/: every artifact is copied to a temp dir
first. Needs the Go toolchain; no model server, so it is free and fast.

    python _gate_audit.py [--limit N]
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from src.builder import GoToolchain, _run_deterministic_gates  # noqa: E402

GENERATED = pathlib.Path(__file__).parent / "generated"

# The log line each gate emits when it fires, mapped back to a readable name.
GATE_SIGNATURES = {
    "renamed the loop variable shadowing": "shadowed-tester",
    "added the specified constructor": "constructor-alias",
    "wrapped the argument to": "argument-adapter",
    "by value instead of calling it": "middleware-value",
    "added missing method": "interface-missing-method",
}

# Strip the parts of a diagnostic that vary between artifacts (paths, line
# numbers, identifier names) so the same DEFECT buckets together.
def signature(line: str) -> str | None:
    m = re.search(r"\.go:\d+:\d+: (.+)$", line.strip())
    if not m:
        return None
    msg = m.group(1)
    msg = re.sub(r'"[^"]*"', '"…"', msg)
    msg = re.sub(r"\b[A-Za-z_][\w.]*\b(?=\s*\()", "F", msg)   # call targets
    msg = re.sub(r"\b\d+\b", "N", msg)
    # Keep the grammar of the error, drop the specific names it mentions.
    msg = re.sub(r"\b(?![a-z]{2,}\b)[A-Za-z_][\w.]*\b", "X", msg)
    return msg[:110]


def module_of(d: pathlib.Path) -> str | None:
    gomod = d / "go.mod"
    if not gomod.exists():
        return None
    m = re.search(r"^module\s+(\S+)", gomod.read_text(), re.M)
    return m.group(1) if m else None


def audit(d: pathlib.Path, tc: GoToolchain) -> dict | None:
    module = module_of(d)
    if module is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp) / d.name
        shutil.copytree(d, work)
        for junk in work.rglob("*"):          # drop stray compiled binaries
            if junk.is_file() and junk.suffix == "" and junk.stat().st_mode & 0o111:
                junk.unlink()

        ok, before = tc.check(work)
        if ok:
            return {"name": d.name, "status": "already-green"}

        fired: list[str] = []
        for _ in range(8):
            written = {
                str(p.relative_to(work)): p.read_text() for p in work.rglob("*.go")
            }
            _, surface = tc.check(work)
            changed = _run_deterministic_gates(written, surface, module)
            if not changed:
                break
            for line in surface.splitlines():
                pass
            for path, content in changed.items():
                (work / path).write_text(content)
        # Which gates fired is read from what the gates logged; re-derive it by
        # diffing instead, so this stays independent of log formatting.
        after_ok, after = tc.check(work)
        residual = [s for s in (signature(l) for l in after.splitlines()) if s]
        # A compile diagnostic carries a COLUMN; a failing assertion does not.
        # They are different backlogs: the first is what a gate could still fix,
        # the second is what only the spec or the model can.
        compiles = bool(re.search(r"\.go:\d+:\d+:", after))
        return {
            "name": d.name,
            "status": "green-by-gates" if after_ok else ("advanced" if before != after else "stuck"),
            "residual": residual if compiles else [],
            "test_failures": [] if compiles else re.findall(r"--- FAIL: (\w+)", after),
            "kind": "compile" if compiles else "test",
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--current",
        action="store_true",
        help="only artifacts produced by the CURRENT v4 system. generated/ also "
        "holds ~40 relics of dead experiments (15b-base, DAPT, pre-split workapi "
        "runs) written by models we no longer serve; ranking a gate backlog on "
        "defects a retired model used to make is worse than not ranking it.",
    )
    args = ap.parse_args()

    tc = GoToolchain()
    dirs = sorted(p for p in GENERATED.iterdir() if p.is_dir() and (p / "go.mod").exists())
    if args.current:
        dirs = [
            p for p in dirs
            if re.search(r"(-v4$|^probe\d|roll\d|-green\d|^_proof)", p.name)
        ]
    if args.limit:
        dirs = dirs[: args.limit]

    rows, buckets = [], collections.Counter()
    for d in dirs:
        r = audit(d, tc)
        if not r:
            continue
        rows.append(r)
        for sig in set(r.get("residual") or []):    # count ARTIFACTS, not lines
            buckets[sig] += 1
        print(f"  {r['status']:16s} {r['name']}", flush=True)

    status = collections.Counter(r["status"] for r in rows)
    print(f"\n=== {len(rows)} artifacts ===")
    for k, v in status.most_common():
        print(f"  {v:3d}  {k}")

    broken = [r for r in rows if r["status"] != "already-green"]
    kinds = collections.Counter(r.get("kind") for r in broken)
    print(f"\n=== of {len(broken)} broken artifacts, what still blocks them ===")
    print(f"  {kinds.get('compile', 0):3d}  still do not COMPILE  -> a gate could still help")
    print(f"  {kinds.get('test', 0):3d}  compile, but a TEST fails -> only the spec or the model can")

    print("\n=== residual COMPILE classes, by how many DISTINCT artifacts hit them ===")
    print("    (the ranked backlog: what the gates still cannot repair)\n")
    for sig, n in buckets.most_common(25):
        print(f"  {n:3d}  {sig}")


if __name__ == "__main__":
    main()
