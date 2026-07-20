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

        for _ in range(8):
            written = {
                str(p.relative_to(work)): p.read_text() for p in work.rglob("*.go")
            }
            _, surface = tc.check(work)
            changed = _run_deterministic_gates(written, surface, module)
            if not changed:
                break
            for path, content in changed.items():
                (work / path).write_text(content)
        # Status is derived by DIFFING (did the tree change, did it reach green),
        # not by parsing gate logs — so it stays independent of log formatting.
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


# Messages a mechanism emits ONLY on a path we never expect in an A/B run, or on
# an error path we hope never runs. Everything else that never fires is a
# question worth asking.
_EXPECTED_SILENT = (
    "maintain", "review", "trace write failed", "spec-lint",
    "fix-round budget scaled to",   # inert at --max-fix-rounds 5: ceil(19/4) == 5
    "rejected fix of",              # a guard; never needing it is the good outcome
    "restored go.mod",              # a guard: go.mod is deterministic-by-construction and
                                    # never handed to the model, so it is never malformed and
                                    # never needs restoring — silent is the healthy state
)


def audit_mechanisms() -> None:
    """Which mechanisms never fire?

    Five of this week's seven system bugs were found by exactly this question, and
    each time I asked it with an ad-hoc grep. It should not be ad-hoc. A mechanism
    that has never announced itself across every run we have ever done is either
    dead code or — far worse, and this is what kept happening — silently guarded
    shut while looking perfectly healthy. Best-of-N had never selected a candidate
    in its life; the verified fix had never verified one; the middleware gate had
    never fired on the wall it was written for.
    """
    src = (pathlib.Path(__file__).parent / "src" / "builder.py").read_text()
    msgs = sorted({
        m.strip() for m in re.findall(r'_log\(\s*f?"(?:\s*)([^"{]{8,44})', src)
        if m.strip()
    })
    logs = sorted((pathlib.Path(__file__).parent / "logs").glob("ab-*.log"))
    blob = "\n".join(p.read_text(errors="ignore") for p in logs)

    print(f"=== {len(msgs)} mechanisms, checked against {len(logs)} real runs ===\n")
    silent = [m for m in msgs if blob.count(m) == 0]
    flagged = [m for m in silent if not any(e in m.lower() for e in _EXPECTED_SILENT)]
    for m in flagged:
        print(f"  ✗ NEVER FIRED  {m}")
    print(f"\n  {len(flagged)} unexplained · {len(silent) - len(flagged)} expected-silent "
          f"(maintain/review/error paths) · {len(msgs) - len(silent)} healthy")
    if flagged:
        print("\n  A mechanism that cannot be observed working cannot be trusted to\n"
              "  work. Check each: is it new, or is it guarded shut?")


def audit_regression() -> int:
    """Do the artifacts the gates can fully repair STILL go green?

    A gate change that breaks the chain would pass every unit test — they check
    one gate on one fixture — and would only be caught by a sweep, which costs
    hours of GPU. But the archiver keeps every project the model has ever broken,
    and the chain can be re-run over all of them for free. Those that reach green
    by the gates alone are a lock: if one stops, something regressed.

    Returns the number that regressed, so this can gate a commit.
    """
    tc = GoToolchain()
    # An archive with no .go files carries no evidence: a run killed during
    # generation leaves a go.mod and nothing else. The gates cannot move a project
    # that has no code, so every such shell counts as STUCK — and the scoreboard
    # then reports the operator's own kill-debris as a machinery regression. Four
    # of them turned "0 stuck" into "4 stuck" without a single gate changing.
    # A directory with no Go in it is not a failure; it is an absence.
    reds = sorted(
        p for p in GENERATED.iterdir()
        if p.is_dir()
        and (p / "go.mod").exists()
        and p.name.startswith(("_fail", "_proof"))
        and any(p.rglob("*.go"))
    )
    if not reds:
        print("no archived failures yet — nothing to lock")
        return 0

    print(f"=== driving the gate chain over {len(reds)} archived RED artifacts ===\n")
    green, advanced, stuck = [], [], []
    for d in reds:
        module = module_of(d)
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp) / d.name
            shutil.copytree(d, work)
            ok, before = tc.check(work)
            for _ in range(20):
                written = {
                    str(p.relative_to(work)): p.read_text() for p in work.rglob("*.go")
                }
                _, surface = tc.check(work)
                changed = _run_deterministic_gates(written, surface, module)
                if not changed:
                    break
                for path, content in changed.items():
                    (work / path).write_text(content)
            after_ok, after = tc.check(work)
        if after_ok:
            green.append(d.name)
        elif before != after:
            advanced.append(d.name)
        else:
            stuck.append(d.name)
        mark = "GREEN-BY-GATES" if after_ok else ("advanced" if before != after else "STUCK")
        print(f"  {mark:15s} {d.name}")

    print(f"\n  {len(green)} green by the gates alone · {len(advanced)} advanced · "
          f"{len(stuck)} stuck")
    if stuck:
        print("\n  STUCK means the gates changed NOTHING. That is one of three "
              "things,\n  and they are not the same:\n"
              "    - a gate that stopped firing            (a REGRESSION — fix it)\n"
              "    - a defect class we have never seen     (a BACKLOG item — build it)\n"
              "    - a defect the compiler cannot name     (the HONEST FLOOR — leave it)\n"
              "  The third is real and it is not a failure. An unregistered route, an\n"
              "  uncalled method, a middleware that is declared and never applied: all\n"
              "  are legal Go. They build, they vet, and the compiler has nothing to\n"
              "  say — so there is no sentence for a gate to listen for. Only a test\n"
              "  notices. Do not chase those with gates; name them in the spec.")
    return len(stuck)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--regress",
        action="store_true",
        help="re-drive the gate chain over every ARCHIVED red artifact and report "
        "which still reach green. A gate change that breaks the chain passes every "
        "unit test and is otherwise only caught by a sweep costing hours of GPU.",
    )
    ap.add_argument(
        "--mechanisms",
        action="store_true",
        help="audit which machinery never fires in any real run, instead of "
        "auditing the artifacts. This is the check that found best-of-N never "
        "selecting, the verified fix never verifying, and the middleware gate "
        "never firing on the wall it was written for.",
    )
    ap.add_argument(
        "--current",
        action="store_true",
        help="only artifacts produced by the CURRENT v4 system. generated/ also "
        "holds ~40 relics of dead experiments (15b-base, DAPT, pre-split workapi "
        "runs) written by models we no longer serve; ranking a gate backlog on "
        "defects a retired model used to make is worse than not ranking it.",
    )
    args = ap.parse_args()

    if args.mechanisms:
        audit_mechanisms()
        return

    if args.regress:
        raise SystemExit(1 if audit_regression() else 0)

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
