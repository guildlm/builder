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


def _tf_reverse_sort(text: str) -> str | None:
    """taskflow: reverse the sorted-by-ID order in BOTH list methods (ascending -> descending).

    Deterministic by construction (unlike a DROP, whose catch depends on Go map-iteration
    randomness). Used once a spec has a real order-asserting test — an ascending assertion
    catches a descending sort every run. Mirrors the taskapi positive control.
    """
    a = "return out[i].ID < out[j].ID"
    if text.count(a) != 2:  # one invariant, two mirrored list methods
        return None
    return text.replace(a, "return out[i].ID > out[j].ID")


def _ua_drop_sort(text: str) -> str | None:
    """usersapi: remove the sorted-by-ID guarantee from List (single method)."""
    line = "\tsort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })"
    if text.count(line) != 1:
        return None
    text = text.replace(line, "\t// MUTANT: sorted-by-ID invariant removed")
    return text.replace('\t"sort"\n', "")


def _ua_reverse_sort(text: str) -> str | None:
    """usersapi: reverse the sorted-by-ID order in List (ascending -> descending). Deterministic."""
    a = "return out[i].ID < out[j].ID"
    if text.count(a) != 1:
        return None
    return text.replace(a, "return out[i].ID > out[j].ID")


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


def _tap_drop_tasks_sort(text: str) -> str | None:
    """taskapipro: drop the ListTasks sort ONLY (ListProjects sort + import stay).

    This is the concrete, deterministic proof of the blast-radius damage recorded in
    guildlm-session-resume: a spec edit SILENTLY DELETED this artifact's TestListSorted
    (tasks). ListProjects still has TestListProjectsSorted (itself flaky), but nothing
    defends the tasks-list order anymore — drop that one sort and the suite is green
    10/10. Anchor on the ListProjects boundary so only the tasks-half sort is touched.
    """
    marker = "func (s *MemStore) ListProjects"
    idx = text.find(marker)
    if idx < 0:
        return None
    head, tail = text[:idx], text[idx:]
    line = "\tsort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })"
    if head.count(line) != 1:  # exactly one sort in the tasks half
        return None
    head = head.replace(line, "\t// MUTANT: ListTasks sorted-by-ID removed")
    return head + tail


def _tap_reverse_tasks_sort(text: str) -> str | None:
    """taskapipro: reverse the ListTasks sort ONLY (ascending -> descending; ListProjects stays).

    Deterministic (unlike the drop, which leaves the tasks list in map order). Anchor on the
    ListProjects boundary so only the tasks-half sort flips. Caught by the api-layer TestListLimit
    once it asserts all[0].ID == "1" (defending tasks order without touching the crowded store test).
    """
    marker = "func (s *MemStore) ListProjects"
    idx = text.find(marker)
    if idx < 0:
        return None
    head, tail = text[:idx], text[idx:]
    a = "return out[i].ID < out[j].ID"
    if head.count(a) != 1:
        return None
    head = head.replace(a, "return out[i].ID > out[j].ID")
    return head + tail


def _bs_drop_clear_guard(text: str) -> str | None:
    """bitset: remove Clear's out-of-range guard so Clear(i) beyond words panics.

    Spec: "if i/64 is beyond the current words, it is already clear — do nothing, do
    not panic." The test does Test(200) (beyond the slice) but never Clear(200), so
    the guard is undefended: drop it and the suite stays green, yet Clear(200) on a
    small set now panics (validated with a probe). The unique `&^=` line anchors it.
    """
    blk = ("\twordIndex := i / 64\n\tif wordIndex < len(b.words) {\n"
           "\t\tb.words[wordIndex] &^= uint64(1) << uint(i%64)\n\t}\n")
    if text.count(blk) != 1:
        return None
    return text.replace(
        blk, "\twordIndex := i / 64\n\tb.words[wordIndex] &^= uint64(1) << uint(i%64)\n")


def _tapi_create_skip_validate(text: str) -> str | None:
    """tasks-api: make Create skip t.Validate() (Update still validates).

    Both Create and Update call t.Validate() after decoding. Update's call is defended
    (TestUpdateInvalid PUTs {"title":""} -> 400). Create's is NOT: TestInvalid400 posts
    MALFORMED json, which trips 400 in the DECODER, never reaching Validate. So a Create
    that skips validation ships green — a blank-title POST returns 201 (probe-confirmed).
    The spec even shows this code twice and warns about exactly this omission. Anchor on
    `a.store.Create(t)`, unique to Create.
    """
    anchor = ('\tif err := t.Validate(); err != nil {\n'
              '\t\twriteJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})\n'
              '\t\treturn\n\t}\n'
              '\tif err := a.store.Create(t); err != nil {')
    if text.count(anchor) != 1:
        return None
    return text.replace(
        anchor, '\t// MUTANT: Create skips t.Validate()\n\tif err := a.store.Create(t); err != nil {')


def _wp_unbounded(text: str) -> str | None:
    """workerpool: spawn one goroutine per item instead of `workers` (unbounded).

    ParallelMap must use "at most `workers` goroutines". The output (input order +
    once-per-item count) is identical whether it runs 2 goroutines or one-per-item, so
    both output-checking tests pass on the mutant. A concurrency probe confirms the
    real behaviour change: correct code peaks at `workers`, the mutant peaks at
    len(items). An invariant with NO OUTPUT SIGNATURE — coverage and green cannot see it.
    """
    a = "for w := 0; w < workers; w++ {"
    if text.count(a) != 1:
        return None
    return text.replace(a, "for w := 0; w < len(items); w++ {")


def _wv_drop_delete(text: str) -> str | None:
    """walkv: drop Delete's in-session map removal (keep the DEL log write).

    Delete appends a DEL record AND deletes from the in-memory map. TestSetGet never
    calls Delete; TestRecoveryAfterReopen calls it but only checks the result AFTER a
    Close+reopen, where replay's DEL case rebuilds the map. So the LIVE map delete is
    undefended: drop it and the suite stays green, yet a same-session Delete-then-Get
    still returns the key (validated with a probe). Anchor on the DEL WriteString,
    unique to Delete (replay's delete is triple-tab-indented).
    """
    anchor = ('+ key + "\\n"); err != nil {\n\t\treturn err\n\t}\n'
              '\tdelete(s.m, key)\n\treturn nil\n}')
    if text.count(anchor) != 1:
        return None
    repl = ('+ key + "\\n"); err != nil {\n\t\treturn err\n\t}\n'
            '\t// MUTANT: in-session map delete removed\n\treturn nil\n}')
    return text.replace(anchor, repl)


def _ls_flip_primary(text: str) -> str | None:
    """logstats: reverse Report's PRIMARY sort (Count descending -> ascending).

    The slice var name varies by regen (stats/report); match either (exact-string, no regex).
    """
    for v in ("report", "stats"):
        a = f"return {v}[i].Count > {v}[j].Count"
        if text.count(a) == 1:
            return text.replace(a, f"return {v}[i].Count < {v}[j].Count")
    return None


def _ls_drop_tiebreak(text: str) -> str | None:
    """logstats: drop Report's TIE-BREAK (Path ascending on equal Count)."""
    blk = ("\t\tif stats[i].Count == stats[j].Count {\n"
           "\t\t\treturn stats[i].Path < stats[j].Path\n\t\t}\n")
    if text.count(blk) != 1:
        return None
    return text.replace(blk, "\t\t// MUTANT: tie-break (Path asc on equal Count) removed\n")


def _ls_reverse_tiebreak(text: str) -> str | None:
    """logstats: reverse Report's TIE-BREAK (Path ascending -> descending on equal Count).

    Deterministic (unlike a DROP, which leaves equal-Count elements in pdqsort's
    unspecified order). A test that gives two paths the SAME Count and asserts Path
    ascending catches the reversed tie-break every run.

    The slice var name varies by regen (stats/report); match either (exact-string, no regex).
    """
    for v in ("report", "stats"):
        a = f"return {v}[i].Path < {v}[j].Path"
        if text.count(a) == 1:
            return text.replace(a, f"return {v}[i].Path > {v}[j].Path")
    return None


def _kv_drop_content_type(text: str) -> str | None:
    """kvservice: drop the `Content-Type: text/plain` header on GET.

    main.go spec: "GET /kv/{key} returns the value as text/plain". The tests assert only the
    status code (200) and the body ("hi"), never the Content-Type, so removing the header ships
    green — validated model-free. A newly-found hole in a previously-unexamined spec.
    """
    for line in ('\t\tw.Header().Set("Content-Type", "text/plain")\n',
                 '\tw.Header().Set("Content-Type", "text/plain")\n'):
        if text.count(line) == 1:
            return text.replace(line, "\t\t// MUTANT: Content-Type text/plain removed\n")
    return None


def _ja_drop_content_type(text: str) -> str | None:
    """jsonapi: drop the `Content-Type: application/json` header on the echo response."""
    for line in ('\t\tw.Header().Set("Content-Type", "application/json")\n',
                 '\tw.Header().Set("Content-Type", "application/json")\n'):
        if text.count(line) == 1:
            return text.replace(line, "\t\t// MUTANT: Content-Type application/json removed\n")
    return None


def _pq_reverse_less(text: str) -> str | None:
    """priorityqueue: reverse the min-heap comparison (< -> >) so it pops highest-first.

    A CAUGHT control on an algorithm spec: TestPopOrderByPriority pushes 3,1,2 and asserts the
    pop order is 1,2,3, so flipping Less makes it pop 3,2,1 -> red. The invariant IS the test
    subject here (why the library specs are well-defended), recorded as a positive control.
    """
    a = "return h[i].Priority < h[j].Priority"
    if text.count(a) != 1:
        return None
    return text.replace(a, "return h[i].Priority > h[j].Priority")


def _ja_drop_405(text: str) -> str | None:
    """jsonapi: drop the non-POST -> 405 method guard so any method falls through."""
    blk = ("\t\tif r.Method != http.MethodPost {\n"
           '\t\t\thttp.Error(w, "method not allowed", http.StatusMethodNotAllowed)\n'
           "\t\t\treturn\n\t\t}\n")
    if text.count(blk) != 1:
        return None
    return text.replace(blk, "\t\t// MUTANT: non-POST 405 guard removed\n")


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
     _tf_reverse_sort),                              # was drop (flaky); now reverse (deterministic) — CAUGHT once TestListSorted exists
    ("taskflow", "models.go",
     "Task.Validate rejects a status outside {todo,doing,done}",
     _tf_drop_status),                               # CAUGHT (fix arc #1): TestCreateInvalid posts {"title":"x","status":"nope"}
    # --- usersapi (added 2026-07-18): one guard + the sorted-by-ID hole again ---
    ("usersapi", "store.go",
     "duplicate User ID -> ErrExists (409)",
     _ua_drop_dup),                                  # CAUGHT (TestDuplicateReturns409)
    ("usersapi", "store.go",
     "List returns users sorted by ID (deterministic output)",
     _ua_reverse_sort),                              # was drop (flaky); now reverse (deterministic) — CAUGHT once an order test exists
    # --- logstats (added 2026-07-18): a SPLIT sort — half defended, half not ---
    ("logstats", "stats.go",
     "Report ranks paths by Count descending",
     _ls_flip_primary),                              # CAUGHT (TestConsume asserts report[0]==/a, Count 2>1)
    ("logstats", "stats.go",
     "Report breaks Count ties by Path ascending (deterministic)",
     _ls_reverse_tiebreak),                          # was drop (leaves equal-Count in pdqsort order); now reverse (deterministic) — CAUGHT once a two-equal-Count test exists
    # --- taskapi (added 2026-07-18): the POSITIVE control for the sort hole ---
    ("taskapi", "internal/store/memory.go",
     "List sorted by ID — DEFENDED (contrast: taskflow/usersapi drop it)",
     _ta_reverse_sort),                              # CAUGHT (TestListSorted + TestListProjectsSorted)
    # --- taskapipro (added 2026-07-18): the blast-radius damage, made concrete ---
    ("taskapipro", "internal/store/memory.go",
     "ListTasks sorted by ID (its TestListSorted was deleted by a spec edit)",
     _tap_reverse_tasks_sort),                       # was drop (flaky); now reverse (deterministic) — CAUGHT once TestListLimit asserts all[0].ID
    # --- bitset (added 2026-07-18): a required no-panic guard nobody exercises ---
    ("bitset", "bitset.go",
     "Clear(i) beyond the words slice must not panic",
     _bs_drop_clear_guard),                          # CAUGHT (fix arc #3): TestSetTestClear now calls Clear(200)
    # --- walkv (added 2026-07-18): Delete's LIVE effect is only seen via replay ---
    ("walkv", "store.go",
     "Delete removes the key from the in-memory map (not just the log)",
     _wv_drop_delete),                               # CAUGHT (fix arc #4): same-session Get("gone") asserted before Close
    # --- workerpool (added 2026-07-18): an invariant with no output signature ---
    ("workerpool", "pool.go",
     "ParallelMap uses AT MOST `workers` goroutines (bounded concurrency)",
     _wp_unbounded),                                 # CAUGHT (fix arc #7): TestParallelMapBoundedConcurrency probes peak goroutines
    # --- tasks-api (added 2026-07-18): right status code, wrong trigger ---
    ("tasks-api", "handlers.go",
     "Create validates the body (blank title -> 400, not stored)",
     _tapi_create_skip_validate),                    # CAUGHT (fix arc #2): TestCreateInvalid posts well-formed blank title -> 400
    # --- kvservice (added 2026-07-19): a spec-required response header nobody asserts ---
    ("kvservice", "main.go",
     "GET returns the value as text/plain (Content-Type header)",
     _kv_drop_content_type),                         # CAUGHT (fix arc #10): TestPutThenGet asserts Content-Type text/plain
    # --- jsonapi (added 2026-07-19): a response header and an error path nobody asserted ---
    ("jsonapi", "main.go",
     "echo response is Content-Type application/json",
     _ja_drop_content_type),                         # CAUGHT (fix arc #11): TestEcho asserts application/json
    ("jsonapi", "main.go",
     "non-POST /echo returns 405 (method guard)",
     _ja_drop_405),                                  # CAUGHT (fix arc #11): a GET /echo asserts 405
    # --- priorityqueue (added 2026-07-19): a positive control on an algorithm spec ---
    ("priorityqueue", "pq.go",
     "min-heap pops lowest priority first",
     _pq_reverse_less),                              # CAUGHT control: TestPopOrderByPriority asserts pop order 1,2,3
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
