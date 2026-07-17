#!/usr/bin/env python3
"""Does each spec's suite DEFEND its impl-required invariants? Mutation, codified.

Coverage measures lines run, not invariants defended (proven 2026-07-17/18: a
ledger that drops every credit, a rate limiter with no burst cap, an LRU that
forgets to refresh an updated key, an event bus whose Publish blocks on a full
subscriber — all ship GREEN). The only instrument that catches this is a
deliberate break, and this file turns the by-hand breaks into a repeatable suite.

Each entry names a real invariant the impl-spec REQUIRES, a text mutation that
removes it, and the expectation. Run it against an artifact and:
  CAUGHT  = the suite went red -> the invariant is defended (teeth)
  SURVIVED= the suite stayed green on broken code -> the invariant is UNDEFENDED
A mutation that does not apply (code moved / already fixed differently) is
reported, never silently counted as CAUGHT — the deadlock gate taught that an
instrument that cannot fail is decoration.

Every mutation here was validated by hand first: it changes real behaviour, it is
unique in its file, and the correct code passes while the mutant fails IF a test
defends it. Adding an entry means: break a promise the spec actually makes.

Usage: _teeth_suite.py [spec ...]   (default: all specs with a registered mutation)
  needs `go` on PATH; runs `go test -count=1` (cache-safe) per artifact copy.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GEN = ROOT / "generated"


def _drop_line(pattern: str):
    """A mutation that deletes the unique line matching `pattern` (regex)."""
    def apply(text: str) -> str | None:
        rx = re.compile(pattern)
        hits = rx.findall(text)
        if len(hits) != 1:
            return None
        return rx.sub("// MUTANT: invariant removed", text, count=1)
    return apply


def _drop_block(pattern: str):
    """Delete a unique multi-line block matching `pattern` (DOTALL regex)."""
    def apply(text: str) -> str | None:
        rx = re.compile(pattern, re.S)
        if len(rx.findall(text)) != 1:
            return None
        return rx.sub("\n\t// MUTANT: invariant removed\n", text, count=1)
    return apply


# (spec, relative file, description, mutation). One promise per entry.
MUTATIONS = [
    ("ledger", "internal/store/store.go",
     "every credit lands (double-entry: negative postings apply)",
     _drop_line(r"s\.balances\[p\.AccountID\] \+= p\.Amount")),
    ("ledger", "internal/store/memory.go",
     "every credit lands (impl in memory.go variant)",
     _drop_line(r"s\.balances\[p\.AccountID\] \+= p\.Amount")),
    ("ratelimit", "bucket.go",
     "burst capped at capacity after a long idle",
     _drop_block(r"\n\s*if b\.tokens > float64\(b\.capacity\) \{\s*\n\s*b\.tokens = float64\(b\.capacity\)\s*\n\s*\}")),
    ("lrucache", "lru.go",
     "Put on an existing key refreshes recency (move to front)",
     None),  # handled specially below: drop the MoveToFront after a value set
    ("eventbus", "bus.go",
     "Publish is non-blocking on a full subscriber",
     _drop_line(r"\n\s*default:\s*")),
]


def _mutate_lru(text: str) -> str | None:
    """Drop the MoveToFront on the Put-existing branch (the line after a value set)."""
    lines = text.split("\n")
    out, seen_val, done = [], False, False
    for ln in lines:
        if re.search(r"\.value\s*=\s*value", ln):
            seen_val = True
        if seen_val and not done and "MoveToFront" in ln:
            out.append("\t\t// MUTANT: invariant removed")
            done = True
            continue
        out.append(ln)
    return "\n".join(out) if done else None


def _run(spec: str, rel: str, desc: str, mutate) -> tuple[str, str]:
    art = GEN / f"{spec}-v4"
    src = art / rel
    if not src.exists():
        return "SKIP", f"{rel} not in artifact"
    if mutate is None and spec == "lrucache":
        mutate = _mutate_lru
    mutated = mutate(src.read_text()) if mutate else None
    if mutated is None:
        return "NOAPPLY", "mutation did not apply (code moved / already differs)"
    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "proj"
        shutil.copytree(art, work)
        (work / rel).write_text(mutated)
        r = subprocess.run(["go", "test", "-count=1", "-timeout", "60s", "./..."],
                           cwd=work, capture_output=True, text=True)
    return ("CAUGHT", "suite red — defended") if r.returncode != 0 \
        else ("SURVIVED", "GREEN on broken code — UNDEFENDED")


def main() -> int:
    wanted = set(sys.argv[1:])
    rows = [m for m in MUTATIONS if not wanted or m[0] in wanted]
    print(f"{'spec':<12} {'verdict':<9} invariant")
    print("-" * 74)
    undef = 0
    for spec, rel, desc, mut in rows:
        verdict, note = _run(spec, rel, desc, mut)
        if verdict == "SURVIVED":
            undef += 1
        mark = {"CAUGHT": "✓", "SURVIVED": "✗ UNDEFENDED", "NOAPPLY": "· n/a",
                "SKIP": "· skip"}.get(verdict, verdict)
        print(f"{spec:<12} {mark:<9} {desc}")
        if verdict in ("NOAPPLY", "SKIP"):
            print(f"{'':<12} {'':<9} ({note})")
    print("-" * 74)
    print(f"{undef} invariant(s) UNDEFENDED (suite green on broken code).")
    print("SURVIVED = coverage cannot see it; a test never written lowers no number.")
    return 1 if undef else 0


if __name__ == "__main__":
    raise SystemExit(main())
