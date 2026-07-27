#!/usr/bin/env python3
"""Is the corpus being written RIGHT NOW? Ask before measuring it.

Learned twice in one day, the second time expensively. A generation writes its artifact
file by file, so an instrument that reads generated/ mid-run reads a HALF-WRITTEN tree:
    - the teeth suite reported both usersapi invariants "✗ UNDEFENDED (green on broken
      code)" from a tree that held go.mod and store.go and no test files at all;
    - a destructive command run beside a live build cost that build its files and a restart.
Neither failure announced itself. Both look exactly like a result.

So the instruments ask first. Two answers, because the two cases are not the same:
    REFUSE  the artifact you are about to measure is the one being written. Any verdict is
            about a partial tree.
    WARN    something else is generating. Your target is stable, but the corpus around it
            is moving, and a corpus-wide number taken now is not reproducible.

    python _corpus_state.py              # report what is being written, if anything
    python _corpus_state.py --self-test  # parsed from fixed strings; no processes needed
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

OUT_RE = re.compile(r"--out[= ]+(\S+)")
# The commands that write into generated/: a build directly, and the scripts that drive
# them. The drivers matter on their own because a driver spends real time BETWEEN builds —
# `go test -race -count=4` on a fresh artifact, then the next spec — and in that window no
# `guildlm-build main` process exists while the corpus is still very much moving.
#
# Matched by the repo's naming convention rather than by a list of names. The list went
# stale the first time it was tested: four new drivers (_chain_run, _chain_sweep,
# _taskflow_chain_run, _bitset_witness_run) were writing the corpus while this reported
# "clear" between their builds, because they were written after the list was.
WRITER_RE = re.compile(r"guildlm-build\s+main|_rebuild_corpus\.sh|_[a-z0-9_]*(sweep|run)\.sh")


def writers(ps_output: str) -> list[tuple[str, str | None]]:
    """[(command-line, --out target or None)] for every live corpus writer."""
    out = []
    for line in ps_output.splitlines():
        if not WRITER_RE.search(line):
            continue
        if "_corpus_state" in line or "grep" in line:
            continue
        m = OUT_RE.search(line)
        out.append((line.strip(), m.group(1) if m else None))
    return out


def _same_tree(target: str | pathlib.Path, out_arg: str) -> bool:
    """Do a measurement target and a build's --out refer to the same directory?"""
    try:
        a = pathlib.Path(target).resolve()
        b = pathlib.Path(out_arg).resolve()
    except OSError:
        return False
    return a == b or a in b.parents or b in a.parents


def check(target: str | pathlib.Path | None = None, ps_output: str | None = None) -> str:
    """"refuse" / "warn" / "clear" — and it prints the reason itself."""
    if ps_output is None:
        try:
            ps_output = subprocess.run(["ps", "-Ao", "command"], capture_output=True,
                                       text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return "clear"  # cannot ask; do not pretend to know
    live = writers(ps_output)
    if not live:
        return "clear"
    if target is not None:
        for cmd, out_arg in live:
            if out_arg and _same_tree(target, out_arg):
                print(f"REFUSING: {target} is being WRITTEN right now by\n  {cmd[:150]}\n"
                      f"Any verdict here is about a partial tree. Wait for the run to finish.",
                      file=sys.stderr)
                return "refuse"
    names = ", ".join(o or "?" for _, o in live)
    print(f"WARNING: the corpus is moving — {len(live)} generation(s) in flight "
          f"(writing: {names}).\n  A corpus-wide number taken now is not reproducible, and "
          f"a half-written tree with no\n  _test.go survives every mutation. See "
          f"_corpus_state.py.", file=sys.stderr)
    return "warn"


def self_test() -> int:
    sweep = ("bash ./_rebuild_corpus.sh\n"
             "python .venv/bin/guildlm-build main --spec specs/usersapi.yaml "
             "--out ./generated/usersapi-v4 --model x\n"
             "python -m pytest -q\n")
    fails = []
    if len(writers(sweep)) != 2:
        fails.append(f"both the sweep and the build are writers, got {len(writers(sweep))}")
    if writers(sweep)[1][1] != "./generated/usersapi-v4":
        fails.append("the --out target was not parsed")
    if writers("python -m pytest -q\nvim notes.txt\n"):
        fails.append("pytest and an editor are not corpus writers")
    if check("generated/usersapi-v4", sweep) != "refuse":
        fails.append("measuring the tree being written must REFUSE")
    if check("generated/taskflow-v4", sweep) != "warn":
        fails.append("measuring a different tree while a sweep runs must WARN, not refuse")
    if check("generated/taskflow-v4", "python -m pytest -q\n") != "clear":
        fails.append("no writer means clear")
    # A writer with no --out (a sweep script) must not be read as 'refuse' for every target.
    if check("generated/x-v4", "bash ./_sweep.sh a b c\n") != "warn":
        fails.append("a writer with no --out can only warn — it names no target")
    # DRIVERS COUNT AS WRITERS BETWEEN THEIR BUILDS. Each of these spends minutes running
    # go test on a finished artifact before starting the next one, with no guildlm-build
    # process alive; a checker that reads that window as "clear" gives its blessing to
    # exactly the measurement it exists to prevent.
    for driver in ("bash ./_chain_sweep.sh", "bash ./_chain_run.sh usersapi",
                   "/bin/bash ./_bitset_witness_run.sh", "bash ./_taskflow_chain_run.sh"):
        if check("generated/x-v4", driver + "\n") != "warn":
            fails.append(f"{driver} writes the corpus and must at least warn")
    # And the convention must not swallow things that merely look like scripts.
    if writers("bash ./verify_pipeline.sh\nbash ./_mutant_check.sh\n"):
        fails.append("a verifier and a mutation checker do not write the corpus")
    for f in fails:
        print(f"  FAIL: {f}")
    print("self-test: " + ("FAILED" if fails else "ok — refuses the tree in flight, warns about the rest"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    stray = [a for a in sys.argv[1:] if not a.startswith("-")]
    verdict = check(stray[0] if stray else None)
    print(verdict)
    raise SystemExit(0 if verdict != "refuse" else 2)
