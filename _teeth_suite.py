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


def _tf_drop_status(text: str) -> str | None:
    """taskflow: remove the bad-status branch of Task.Validate (title check stays)."""
    blk = ('\tif t.Status != "todo" && t.Status != "doing" && t.Status != "done" {\n'
           '\t\treturn fmt.Errorf("%w: bad status %q", ErrValidation, t.Status)\n'
           '\t}\n')
    if text.count(blk) != 1:
        return None
    return text.replace(blk, "\t// MUTANT: bad-status validation removed\n")


def _tf_drop_dup(text: str) -> str | None:
    """taskflow: remove the duplicate-ID guard in CreateTask."""
    blk = "\tif _, ok := s.tasks[t.ID]; ok {\n\t\treturn ErrExists\n\t}\n"
    if text.count(blk) != 1:
        return None
    return text.replace(blk, "\t// MUTANT: duplicate-ID guard removed\n")


def _tf_drop_paginate_clamp(text: str) -> str | None:
    """taskflow: drop the negative-offset clamp INSIDE paginate, keep the past-end guard."""
    anchor = "\tif offset >= len(items) {\n\t\treturn []T{}\n\t}\n"
    blk = anchor + "\tif offset < 0 {\n\t\toffset = 0\n\t}\n"
    if text.count(blk) != 1:
        return None
    return text.replace(blk, anchor + "\t// MUTANT: negative-offset clamp removed\n")


def _tf_drop_sort(text: str) -> str | None:
    """taskflow: remove the sorted-by-ID guarantee from BOTH mirrored list methods."""
    line = "\tsort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })"
    if text.count(line) != 2:  # one invariant, two mirrored list methods
        return None
    text = text.replace(line, "\t// MUTANT: sorted-by-ID invariant removed")
    return text.replace('\t"sort"\n', "")  # drop the now-unused import so it still compiles


def _ua_drop_sort(text: str) -> str | None:
    """usersapi: remove the sorted-by-ID guarantee from List (single method)."""
    line = "\tsort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })"
    if text.count(line) != 1:
        return None
    text = text.replace(line, "\t// MUTANT: sorted-by-ID invariant removed")
    return text.replace('\t"sort"\n', "")


def _ua_drop_dup(text: str) -> str | None:
    """usersapi: remove the duplicate-ID guard in Create."""
    blk = "\tif _, ok := s.users[u.ID]; ok {\n\t\treturn ErrExists\n\t}\n"
    if text.count(blk) != 1:
        return None
    return text.replace(blk, "\t// MUTANT: duplicate-ID guard removed\n")


def _ta_reverse_sort(text: str) -> str | None:
    """taskapi: reverse the sorted-by-ID order in BOTH list methods (ascending -> descending).

    A DROP mutation here catches only ~probabilistically (map-iteration randomness);
    reversing gives a deterministic wrong order, so the verdict never flakes. taskapi
    is the positive control: the SAME 'List sorted by ID' invariant that taskflow and
    usersapi leave undefended is robustly defended here (TestListSorted +
    TestListProjectsSorted both insert out of order and assert the sorted result).
    """
    a = "return out[i].ID < out[j].ID"
    if text.count(a) != 2:
        return None
    return text.replace(a, "return out[i].ID > out[j].ID")


def _ls_flip_primary(text: str) -> str | None:
    """logstats: reverse Report's PRIMARY sort (Count descending -> ascending)."""
    a = "\t\treturn stats[i].Count > stats[j].Count"
    if text.count(a) != 1:
        return None
    return text.replace(a, "\t\treturn stats[i].Count < stats[j].Count")


def _ls_drop_tiebreak(text: str) -> str | None:
    """logstats: drop Report's TIE-BREAK (Path ascending on equal Count)."""
    blk = ("\t\tif stats[i].Count == stats[j].Count {\n"
           "\t\t\treturn stats[i].Path < stats[j].Path\n\t\t}\n")
    if text.count(blk) != 1:
        return None
    return text.replace(blk, "\t\t// MUTANT: tie-break (Path asc on equal Count) removed\n")


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
    ("workapi", "internal/worker/worker.go",
     "Stop() drains in-flight events (wg.Wait before returning)",
     _drop_line(r"\n\s*w\.wg\.Wait\(\)")),
    # --- taskflow (added 2026-07-18): two defended controls + two NEW holes ---
    ("taskflow", "store.go",
     "duplicate Task ID -> ErrExists (409)",
     _tf_drop_dup),                                  # CAUGHT (TestCreateDuplicate)
    ("taskflow", "pagination.go",
     "paginate clamps a negative offset (no panic, exact count)",
     _tf_drop_paginate_clamp),                       # CAUGHT (TestPaginateNegativeOffset)
    ("taskflow", "store.go",
     "List methods return items sorted by ID",
     _tf_drop_sort),                                 # HOLE: no test asserts order
    ("taskflow", "models.go",
     "Task.Validate rejects a status outside {todo,doing,done}",
     _tf_drop_status),                               # HOLE: TestCreateInvalid trips on empty title, never a bad status
    # --- usersapi (added 2026-07-18): one guard + the sorted-by-ID hole again ---
    ("usersapi", "store.go",
     "duplicate User ID -> ErrExists (409)",
     _ua_drop_dup),                                  # CAUGHT (TestDuplicateReturns409)
    ("usersapi", "store.go",
     "List returns users sorted by ID (deterministic output)",
     _ua_drop_sort),                                 # HOLE: TestListReturnsAll checks len==2, never order
    # --- logstats (added 2026-07-18): a SPLIT sort — half defended, half not ---
    ("logstats", "stats.go",
     "Report ranks paths by Count descending",
     _ls_flip_primary),                              # CAUGHT (TestConsume asserts report[0]==/a, Count 2>1)
    ("logstats", "stats.go",
     "Report breaks Count ties by Path ascending (deterministic)",
     _ls_drop_tiebreak),                             # HOLE: no test ever has two equal-Count paths
    # --- taskapi (added 2026-07-18): the POSITIVE control for the sort hole ---
    ("taskapi", "internal/store/memory.go",
     "List sorted by ID — DEFENDED (contrast: taskflow/usersapi drop it)",
     _ta_reverse_sort),                              # CAUGHT (TestListSorted + TestListProjectsSorted)
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
