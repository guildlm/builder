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


def spec_of(name: str) -> str:
    """Which SPEC produced this artifact. probe1/probe2/probe3 and
    tasks-api-roll4/roll5 are the same spec rolled repeatedly, and a defect seen
    in all of them is one spec's quirk, not a broad class."""
    n = re.sub(r"^_(fail|proof)-", "", name)
    n = re.sub(r"-\d{6,}$", "", n)                       # archive timestamp
    n = re.sub(r"(-v4|-green\d*|-roll\d*|\d+)$", "", n)  # run suffixes
    return re.sub(r"^probe.*", "tasks-api-noshadownudge", n) or name


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
            "assertions": [] if compiles else assertion_shapes(after),
            "kind": "compile" if compiles else "test",
        }


# `    router_test.go:44: handler returned wrong status code: got 201 want 409`
_ASSERT_RE = re.compile(r"^\s+\w[\w./-]*\.go:\d+:\s*(.+)$", re.M)


def assertion_shapes(output: str) -> list[str]:
    """A failing assertion's MESSAGE, with the specifics filed off, so the same
    mistake buckets together across specs. This is the OTHER backlog: defects that
    compile fine and fail at runtime. No gate can reach them — they become prompt
    defaults (as `isolate state, then seed it` did, after the same mistake showed
    up in six specs) or spec clarifications."""
    out = []
    for msg in _ASSERT_RE.findall(output):
        m = re.sub(r"\b\d+\b", "N", msg)
        m = re.sub(r'"[^"]*"', '"…"', m)
        m = re.sub(r"\s+", " ", m).strip()
        out.append(m[:100])
    return out


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

    rows = []
    by_spec: dict[str, set[str]] = collections.defaultdict(set)
    asserts_by_spec: dict[str, set[str]] = collections.defaultdict(set)
    for d in dirs:
        r = audit(d, tc)
        if not r:
            continue
        rows.append(r)
        for a in set(r.get("assertions") or []):
            asserts_by_spec[a].add(spec_of(d.name))
        # Count DISTINCT SPECS, not artifacts. probe1/probe2/probe3 are the same
        # spec rolled three times; counting them as three sightings of a defect
        # makes one spec's quirk outrank a class that really is broad. The first
        # run of this audit ranked `too many arguments in call to newAPI` top —
        # four artifacts, all of them the same probe spec.
        for sig in set(r.get("residual") or []):
            by_spec[sig].add(spec_of(d.name))
        print(f"  {r['status']:16s} {r['name']}", flush=True)

    buckets = collections.Counter({sig: len(s) for sig, s in by_spec.items()})

    status = collections.Counter(r["status"] for r in rows)
    print(f"\n=== {len(rows)} artifacts ===")
    for k, v in status.most_common():
        print(f"  {v:3d}  {k}")

    broken = [r for r in rows if r["status"] != "already-green"]
    kinds = collections.Counter(r.get("kind") for r in broken)
    print(f"\n=== of {len(broken)} broken artifacts, what still blocks them ===")
    print(f"  {kinds.get('compile', 0):3d}  still do not COMPILE  -> a gate could still help")
    print(f"  {kinds.get('test', 0):3d}  compile, but a TEST fails -> only the spec or the model can")

    a_buckets = collections.Counter({a: len(s) for a, s in asserts_by_spec.items()})
    print("\n=== failing ASSERTIONS, by how many DISTINCT SPECS hit them ===")
    print("    (the semantic backlog: no gate can reach these — they become")
    print("     prompt defaults or spec clarifications)\n")
    for a, n in a_buckets.most_common(15):
        print(f"  {n:3d}  {a}")

    print("\n=== residual COMPILE classes, by how many DISTINCT SPECS hit them ===")
    print("    (the ranked backlog: what the gates still cannot repair)\n")
    for sig, n in buckets.most_common(25):
        print(f"  {n:3d}  {sig}")


if __name__ == "__main__":
    main()
