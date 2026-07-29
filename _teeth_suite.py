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


def _reverse_id_sort(n: int):
    """Reverse `out[i].ID < out[j].ID` in exactly `n` mirrored list methods (ascending -> descending).

    Deterministic by construction — an ascending-order assertion catches a descending sort every
    run, unlike a DROP whose catch depends on Go map-iteration randomness. `n` pins how many
    mirrored list methods share the invariant, so a regen that adds or removes a method reports
    NOAPPLY instead of a false verdict. Used once a spec has a real order-asserting test; taskapi
    is the positive control (robustly defended) that taskflow/usersapi leave open.

    Matched by SHAPE, not by the slice's name. It used to hardcode `out[i]`, and a fresh
    coder that called the slice `users` produced NOAPPLY — a check that silently did not
    run, which under a "must not regress" heading reads as a pass. The backreference keeps
    the two indexes bound to the SAME identifier, so this still cannot straddle two
    different slices, and the count test below is untouched.
    """
    _CMP = re.compile(r"return (\w+)\[i\]\.ID < \1\[j\]\.ID")

    def apply(text: str) -> str | None:
        if len(_CMP.findall(text)) != n:
            return None
        return _CMP.sub(lambda m: f"return {m.group(1)}[i].ID > {m.group(1)}[j].ID", text)
    return apply


def _reverse_id_sort_site(k: int, total: int):
    """Reverse the k-th (1-based) of `total` mirrored comparators, and ONLY that one.

    WHY THIS EXISTS. `_reverse_id_sort(2)` breaks BOTH of taskflow's list methods in one
    patch, so the suite goes red if EITHER is defended — and taskflow defends exactly one.
    The registry row read CAUGHT under the description "List methods return items sorted by
    ID", plural, while reversing ListProjects on its own left the suite GREEN. A multi-site
    mutation is caught by the strongest site and reports the strength of that site as the
    strength of the promise.

    Measured, not argued: on generated/taskflow-ct, reversing line 63 (ListTasks) is CAUGHT
    and reversing line 104 (ListProjects) SURVIVES. The undefended half is the one whose
    named test — TestListProjectsSorted — the model has now failed to write three draws
    running (FINDING-the-dropped-tests-are-sort-twins.txt).

    `total` is still pinned so a regeneration that adds or removes a list method reports
    NOAPPLY rather than silently grading a different site than the one registered.
    """
    _CMP = re.compile(r"return (\w+)\[i\]\.ID < \1\[j\]\.ID")

    def apply(text: str) -> str | None:
        matches = list(_CMP.finditer(text))
        if len(matches) != total or not (1 <= k <= total):
            return None
        m = matches[k - 1]
        return (text[:m.start()]
                + f"return {m.group(1)}[i].ID > {m.group(1)}[j].ID"
                + text[m.end():])
    return apply


def _drop_exists_guard(index_expr: str):
    """Drop a `if _, ok := <map>[<key>]; ok { return ErrExists }` duplicate-ID guard (unique).

    Tolerant WHERE IT IS SAFE, pinned WHERE IT MUST DISCRIMINATE. Matching the literal
    `index_expr` made this NOAPPLY on a fresh usersapi tree, where the coder wrote
    `m.items` for `s.users` and `exists` for `ok` — the same guard, renamed. But matching
    only by shape broke taskflow, which has TWO ErrExists guards (`s.tasks[t.ID]` and
    `s.projects[p.ID]`): the shape pattern hit both, the count test rejected the pair, and
    a mutation that had been CAUGHT went silently NOAPPLY. I claimed tolerating names cost
    no precision; it cost exactly the precision `index_expr` was there to supply, and the
    full-suite re-run is the only reason that did not ship.

    So: one guard in the file means the rename is unambiguous, take it. Several means the
    file has siblings and only the registered literal can say which one, so demand it.
    """
    _GUARD = re.compile(
        r"[ \t]*if _, (\w+) := [\w.]+\[[\w.]+\]; \1 \{\n\s*return ErrExists\n\s*\}\n")

    def apply(text: str) -> str | None:
        found = _GUARD.findall(text)
        if len(found) == 1:
            return _GUARD.sub("\t// MUTANT: duplicate-ID guard removed\n", text)
        if not found:
            return None
        pinned = re.compile(
            r"[ \t]*if _, (\w+) := " + re.escape(index_expr) + r"; \1 \{\n\s*return ErrExists\n\s*\}\n")
        if len(pinned.findall(text)) != 1:
            return None
        return pinned.sub("\t// MUTANT: duplicate-ID guard removed\n", text)
    return apply


def _drop_content_type(mime: str):
    """Drop the `w.Header().Set("Content-Type", <mime>)` response header (either indent level).

    A spec-required response header a happy-path test leaves unasserted — remove it and the suite
    ships green (validated model-free on kvservice text/plain + jsonapi application/json).
    """
    def apply(text: str) -> str | None:
        for line in (f'\t\tw.Header().Set("Content-Type", "{mime}")\n',
                     f'\tw.Header().Set("Content-Type", "{mime}")\n'):
            if text.count(line) == 1:
                return text.replace(line, "\t\t// MUTANT: Content-Type header removed\n")
        return None
    return apply


def _tf_drop_status(text: str) -> str | None:
    """taskflow: remove the bad-status branch of Task.Validate (title check stays)."""
    # Pinned to the guard's SHAPE, not to its error message. The literal version carried
    # `fmt.Errorf("%w: bad status %q", ErrValidation, t.Status)`, and a regeneration that
    # wrote "invalid status" instead — same behaviour, different words — silently turned
    # this into NOAPPLY. The condition is the invariant; the message is prose.
    rx = re.compile(r'[ \t]*if t\.Status != "todo" && t\.Status != "doing" && '
                    r't\.Status != "done" \{\n.*?\n[ \t]*\}\n', re.S)
    if len(rx.findall(text)) != 1:
        return None
    return rx.sub("\t// MUTANT: bad-status validation removed\n", text)


def _tf_drop_paginate_clamp(text: str) -> str | None:
    """taskflow: drop the negative-offset clamp INSIDE paginate, keep the past-end guard."""
    anchor = "\tif offset >= len(items) {\n\t\treturn []T{}\n\t}\n"
    blk = anchor + "\tif offset < 0 {\n\t\toffset = 0\n\t}\n"
    if text.count(blk) != 1:
        return None
    return text.replace(blk, anchor + "\t// MUTANT: negative-offset clamp removed\n")


def _tap_reverse_tasks_sort(text: str) -> str | None:
    """taskapipro: reverse the ListTasks sort ONLY (ascending -> descending; ListProjects stays).

    Deterministic (unlike the drop, which leaves the tasks list in map order). Anchor on the
    ListProjects boundary so only the tasks-half sort flips. Caught by the api-layer TestListLimit
    once it asserts all[0].ID == "1" (defending tasks order without touching the crowded store test).
    """
    marker = re.search(r"func \(\w+ \*MemStore\) ListProjects", text)
    if not marker:
        return None
    idx = marker.start()
    head, tail = text[:idx], text[idx:]
    # Same backreference trick as _reverse_id_sort: the slice's NAME drifts between runs,
    # the shape does not, and binding both indexes to one identifier keeps the mutation
    # from straddling two different slices.
    cmp_rx = re.compile(r"return (\w+)\[i\]\.ID < \1\[j\]\.ID")
    if len(cmp_rx.findall(head)) != 1:
        return None
    head = cmp_rx.sub(lambda m: f"return {m.group(1)}[i].ID > {m.group(1)}[j].ID", head)
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
    rx = re.compile(r'\+ key \+ "\\n"\); err != nil \{\n\t\treturn err\n\t\}\n'
                    r'\tdelete\(\w+\.\w+, key\)\n\treturn nil\n\}')
    hits = rx.findall(text)
    if len(hits) != 1:
        return None
    repl = ('+ key + "\\n"); err != nil {\n\t\treturn err\n\t}\n'
            '\t// MUTANT: in-session map delete removed\n\treturn nil\n}')
    return rx.sub(lambda _: repl, text)


def _ls_flip_primary(text: str) -> str | None:
    """logstats: reverse Report's PRIMARY sort (Count descending -> ascending).

    The slice var name varies by regen (stats/report); match either (exact-string, no regex).
    """
    for v in ("report", "stats"):
        a = f"return {v}[i].Count > {v}[j].Count"
        if text.count(a) == 1:
            return text.replace(a, f"return {v}[i].Count < {v}[j].Count")
    return None


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


def _sh_redirect_302(text: str) -> str | None:
    """shortener: change the redirect status 301 -> 302 (CAUGHT control: TestRedirectFound pins 301)."""
    a = "http.Redirect(w, r, link.URL, http.StatusMovedPermanently)"
    if text.count(a) != 1:
        return None
    return text.replace(a, "http.Redirect(w, r, link.URL, http.StatusFound)")


def _jc_marshal_nanos(text: str) -> str | None:
    """jsoncodec: marshal the timestamp as nanoseconds instead of unix seconds (CAUGHT control)."""
    a = "e.At.Unix()"
    if text.count(a) != 1:
        return None
    return text.replace(a, "e.At.UnixNano()")


def _ee_break_multiply(text: str) -> str | None:
    """expreval: turn multiplication into addition so operator precedence breaks (CAUGHT control)."""
    a = "result *= right"
    if text.count(a) != 1:
        return None
    return text.replace(a, "result += right")


def _ds_break_reverse(text: str) -> str | None:
    """demo-small: break Reverse's swap loop so it returns the input unchanged (CAUGHT control)."""
    a = "for i, j := 0, len(runes)-1; i < j; i, j = i+1, j-1 {"
    if text.count(a) != 1:
        return None
    return text.replace(a, "for i, j := 0, len(runes)-1; i > j; i, j = i+1, j-1 {")


def _nk_break_clamp(text: str) -> str | None:
    """numkit: drop Clamp's upper bound so x above hi is not clamped (CAUGHT control)."""
    blk = "\tif x > hi {\n\t\treturn hi\n\t}\n"
    if text.count(blk) != 1:
        return None
    return text.replace(blk, "\t// MUTANT: upper clamp removed\n")


def _gs_break_len(text: str) -> str | None:
    """genericset: make Len off-by-one (CAUGHT control: TestLen asserts an exact count)."""
    rx = re.compile(r"\treturn len\((\w+)\.m\)\n")
    if len(rx.findall(text)) != 1:
        return None
    return rx.sub(lambda m: f"\treturn len({m.group(1)}.m) + 1\n", text)


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
    # Tolerant of INDENTATION and of HOW the 405 is written. The literal was pinned to two
    # tabs and to http.Error; I widened the indentation first and it still did not apply,
    # because the real difference was the API: the archive writes
    #     http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
    # and a regeneration writes
    #     w.WriteHeader(http.StatusMethodNotAllowed)
    # Both are correct and both return 405. The invariant is "a non-POST gets 405", not
    # which helper delivers it — a distinction I got wrong once before fixing it, and the
    # first comment here confidently named the wrong cause.
    rx = re.compile(r"[ \t]*if r\.Method != http\.MethodPost \{\n"
                    r"[ \t]*(?:http\.Error\([^)]*|w\.WriteHeader\()"
                    r"(?:http\.)?StatusMethodNotAllowed\)\n"
                    r"[ \t]*return\n[ \t]*\}\n")
    if len(rx.findall(text)) != 1:
        return None
    return rx.sub("\t\t// MUTANT: non-POST 405 guard removed\n", text)


# (spec, relative file, description, mutation). One promise per entry.
MUTATIONS = [
    ("ledger", "internal/store/store.go",
     "every credit lands (double-entry: negative postings apply)",
     _drop_line(r"s\.balances\[p\.AccountID\] \+= p\.Amount")),
    ("ledger", "internal/store/memory.go",
     "every credit lands (impl in memory.go variant)",
     # receiver and posting local widened: a regeneration renames `s`/`p`, not `balances`
     _drop_line(r"\w+\.balances\[\w+\.AccountID\] \+= \w+\.Amount")),
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
     _drop_exists_guard("s.tasks[t.ID]")),           # CAUGHT (TestCreateDuplicate)
    ("taskflow", "pagination.go",
     "paginate clamps a negative offset (no panic, exact count)",
     _tf_drop_paginate_clamp),                       # CAUGHT (TestPaginateNegativeOffset)
    # SPLIT BY SITE (2026-07-26). One row reversing both comparators read CAUGHT while the
    # projects half was undefended: the patch breaks two sites, and the tasks test alone
    # turns the suite red. Two rows, one per site, so the scoreboard says which half.
    ("taskflow", "store.go",
     "ListTasks returns tasks sorted by ID",
     _reverse_id_sort_site(1, 2)),                   # CAUGHT — TestListSorted asserts the order
    ("taskflow", "store.go",
     "ListProjects returns projects sorted by ID",
     _reverse_id_sort_site(2, 2)),                   # SURVIVED — TestListProjectsSorted has gone unwritten for 3 draws
    ("taskflow", "models.go",
     "Task.Validate rejects a status outside {todo,doing,done}",
     _tf_drop_status),                               # CAUGHT (fix arc #1): TestCreateInvalid posts {"title":"x","status":"nope"}
    # --- usersapi (added 2026-07-18): one guard + the sorted-by-ID hole again ---
    ("usersapi", "store.go",
     "duplicate User ID -> ErrExists (409)",
     _drop_exists_guard("s.users[u.ID]")),           # CAUGHT (TestDuplicateReturns409)
    ("usersapi", "store.go",
     "List returns users sorted by ID (deterministic output)",
     _reverse_id_sort(1)),                           # was drop (flaky); now reverse (deterministic) — CAUGHT once an order test exists
    # --- ratelimit flow tests (added 2026-07-26): the deny path, defended at last ---
    # Four survivors closed by one spec edit — the flow tests were described in full and
    # named nowhere, so the model wrote none of them. Registered now that they are defended,
    # because an undefended promise nobody registers is a hole that reappears silently.
    ("ratelimit", "middleware.go",
     "429 response carries Retry-After: 1",
     _drop_line(r'[ \t]*w\.Header\(\)\.Set\("Retry-After", *"1"\)\n')),
    ("ratelimit", "middleware.go",
     "over-limit responds 429 TooManyRequests (not 503)",
     lambda t: t.replace("http.StatusTooManyRequests", "http.StatusServiceUnavailable", 1)
     if t.count("http.StatusTooManyRequests") == 1 else None),
    # --- logstats (added 2026-07-18): a SPLIT sort — half defended, half not ---
    ("logstats", "stats.go",
     "Report ranks paths by Count descending",
     _ls_flip_primary),                              # CAUGHT (TestConsume asserts report[0]==/a, Count 2>1)
    ("logstats", "stats.go",
     "Report breaks Count ties by Path ascending (deterministic)",
     _ls_reverse_tiebreak),                          # was drop (leaves equal-Count in pdqsort order); now reverse (deterministic) — CAUGHT once a two-equal-Count test exists
    # --- taskapi (added 2026-07-18): the POSITIVE control for the sort hole ---
    # Split by site for the same reason taskflow's was, and kept as the control that the
    # split is not rigged: taskapi writes BOTH named sort tests and both sites read CAUGHT
    # on their own, where taskflow's projects half SURVIVES alone.
    ("taskapi", "internal/store/memory.go",
     "ListTasks sorted by ID — DEFENDED",
     _reverse_id_sort_site(1, 2)),                   # CAUGHT (TestListSorted)
    ("taskapi", "internal/store/memory.go",
     "ListProjects sorted by ID — DEFENDED (contrast: taskflow drops this half)",
     _reverse_id_sort_site(2, 2)),                   # CAUGHT (TestListProjectsSorted)
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
     _drop_content_type("text/plain")),              # CAUGHT (fix arc #10): TestPutThenGet asserts Content-Type text/plain
    # --- jsonapi (added 2026-07-19): a response header and an error path nobody asserted ---
    ("jsonapi", "main.go",
     "echo response is Content-Type application/json",
     _drop_content_type("application/json")),        # CAUGHT (fix arc #11): TestEcho asserts application/json
    ("jsonapi", "main.go",
     "non-POST /echo returns 405 (method guard)",
     _ja_drop_405),                                  # CAUGHT (fix arc #11): a GET /echo asserts 405
    # --- priorityqueue (added 2026-07-19): a positive control on an algorithm spec ---
    ("priorityqueue", "pq.go",
     "min-heap pops lowest priority first",
     _pq_reverse_less),                              # CAUGHT control: TestPopOrderByPriority asserts pop order 1,2,3
    # --- more library positive controls (added 2026-07-19): invariant IS the test subject ---
    ("demo-small", "stringkit.go",
     "Reverse actually reverses the runes",
     _ds_break_reverse),                             # CAUGHT control: TestReverse asserts exact reversed output
    ("numkit", "numkit.go",
     "Clamp bounds x above hi",
     _nk_break_clamp),                               # CAUGHT control: TestClamp asserts an above-hi value clamps
    ("genericset", "set.go",
     "Len returns the exact element count",
     _gs_break_len),                                 # CAUGHT control: Test... asserts Len()==2
    ("jsoncodec", "event.go",
     "MarshalJSON emits the timestamp as unix SECONDS",
     _jc_marshal_nanos),                             # CAUGHT control: TestMarshalUsesUnixSeconds pins {"at":1000}
    ("expreval", "eval.go",
     "operator precedence: * binds tighter than +",
     _ee_break_multiply),                            # CAUGHT control: TestPrecedenceAndParens asserts 2+3*4==14
    ("shortener", "handlers.go",
     "Redirect responds 301 MovedPermanently",
     _sh_redirect_302),                              # CAUGHT control: TestRedirectFound asserts 301 + Location
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


_GO_TEST = ["go", "test", "-count=1", "-timeout", "60s", "./..."]


def _go_test(work: Path):
    return subprocess.run(_GO_TEST, cwd=work, capture_output=True, text=True)


def _go_build(work: Path):
    return subprocess.run(["go", "build", "./..."], cwd=work, capture_output=True, text=True)


_FAILED_TEST = re.compile(r"^\s*--- FAIL: (\w+)", re.M)


def verdict_for(art: Path, rel: str, mutate, extra: dict | None = None) -> tuple[str, str]:
    """The whole judgement, over ANY project directory — which is what makes it
    checkable. `_run` supplies the archived artifact; --self-test supplies planted
    fixtures whose answer is known in advance.

    `extra` adds files to the copy before ANY test runs — the artifact's own suite plus
    a probe I wrote. It exists so that "is this mutation observable at all?" can be asked
    with the SAME baseline-green and no-tests discipline as "did the suite catch it",
    rather than a second copy-and-run written beside it that would drift. A probe that
    makes the baseline red is a broken probe and reports BASELINE-RED, which is exactly
    the answer wanted: it asserts something the unmutated artifact does not do.
    """
    src = art / rel
    if not src.exists():
        return "SKIP", f"{rel} not in artifact"
    # A TREE WITH NO TESTS SURVIVES EVERYTHING, and that is not a finding about defence.
    # `go test` on a package with no _test.go exits 0, so a mutated tree passes and the
    # verdict reads SURVIVED — "GREEN on broken code — UNDEFENDED", the strongest claim this
    # tool makes — about an artifact nothing was ever asked of. Caught live: the corpus
    # rebuild was mid-generation on usersapi (go.mod and store.go written, no test files
    # yet) and both usersapi invariants were reported UNDEFENDED in that window.
    if not any(art.rglob("*_test.go")):
        return "NOTESTS", "artifact has no _test.go — nothing could have caught anything"
    mutated = mutate(src.read_text()) if mutate else None
    if mutated is None:
        return "NOAPPLY", "mutation did not apply (code moved / already differs)"
    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "proj"
        shutil.copytree(art, work)
        for name, text in (extra or {}).items():
            (work / name).parent.mkdir(parents=True, exist_ok=True)
            (work / name).write_text(text)
        # A CAUGHT/SURVIVED verdict is only meaningful if the UNMUTATED artifact is green:
        # a red baseline makes the mutant red for the wrong reason (fake CAUGHT). This bit the
        # by-hand runs 4x (walkv/usersapi/taskapipro) — encode "check baseline green first."
        base = _go_test(work)
        if base.returncode != 0:
            # CARRY THE REASON. With `extra` in play a red baseline is usually the caller's
            # probe rather than the artifact, and "fix the baseline" sends you to the wrong
            # file: the first probe to hit this had the wrong package clause, which reads as
            # a failed assertion until you see `found packages eval and expreval`.
            why = (base.stdout + base.stderr).strip().splitlines()
            tail = " / ".join(l.strip() for l in why[:2])[:200] if why else ""
            return "BASELINE-RED", ("unmutated artifact already fails — verdict void, fix "
                                    "baseline first" + (f": {tail}" if tail else ""))
        (work / rel).write_text(mutated)
        # A MUTANT THAT DOES NOT COMPILE PROVES NOTHING ABOUT THE TESTS.
        #
        # `go test` exits non-zero when the package fails to BUILD, exactly as it does when an
        # assertion fails, and the code below reads any non-zero as CAUGHT — "suite red —
        # defended". For a mutant the compiler rejects, the suite never ran. The compiler
        # caught it, and the compiler catches it in every project regardless of what the tests
        # assert, which is the opposite of the thing this instrument exists to measure.
        #
        # NOT HYPOTHETICAL, and found by asking rather than by it going wrong (29 July): two
        # entries in MUTATIONS produce SYNTACTICALLY INVALID Go in both generations —
        #     eventbus   bus.go:42:23        syntax error: unexpected { at end of statement
        #     ratelimit  middleware.go:22:3  syntax error: unexpected newline in argument list
        # Their `_drop_line` patterns remove part of a multi-line statement. Each would have
        # been scored CAUGHT under the description "the invariant is defended". They are not
        # weak mutants; they are broken ones, and standard mutation testing excludes
        # non-compiling mutants as INVALID rather than counting them as killed.
        #
        # Reported, never silently folded into CAUGHT — the same rule the deadlock gate and
        # the NOTESTS case taught. A separate verdict means a broken mutation shows up as a
        # thing to FIX instead of inflating the number this whole instrument is here to keep
        # honest.
        built = _go_build(work)
        if built.returncode != 0:
            why = (built.stderr + built.stdout).strip().splitlines()
            first = next((l.strip() for l in why if l.strip().startswith("./")), "")
            kind = "has a syntax error" if "syntax error" in " ".join(why) else "does not compile"
            return "MUTANT-BROKEN", (f"the mutated tree {kind} — the COMPILER rejects it, so a "
                                     f"red suite says nothing about what the tests defend"
                                     + (f": {first[:120]}" if first else ""))
        r = _go_test(work)
    if r.returncode == 0:
        return "SURVIVED", "GREEN on broken code — UNDEFENDED"
    # WHICH test went red is the whole answer when a probe was supplied: red from the
    # artifact's own suite would mean the mutation was defended all along, red from the
    # probe means the probe is what sees it.
    named = sorted(set(_FAILED_TEST.findall(r.stdout + r.stderr)))
    return "CAUGHT", "suite red — defended" + (f" (failing: {', '.join(named)})" if named else "")


def _run(spec: str, rel: str, desc: str, mutate) -> tuple[str, str]:
    if mutate is None and spec == "lrucache":
        mutate = _mutate_lru
    return verdict_for(GEN / f"{spec}-v4", rel, mutate)


_MOD = "module example.com/t\n\ngo 1.23\n"
_IMPL = "package t\n\nfunc Double(n int) int {\n\treturn n * 2\n}\n"
_DEFENDED = ("package t\n\nimport \"testing\"\n\n"
             "func TestDouble(t *testing.T) {\n\tif Double(3) != 6 {\n"
             "\t\tt.Fatalf(\"Double(3) = %d, want 6\", Double(3))\n\t}\n}\n")
# Runs the code and asserts nothing about the value — the shape a green suite hides behind.
_UNDEFENDED = ("package t\n\nimport \"testing\"\n\n"
               "func TestDouble(t *testing.T) {\n\t_ = Double(3)\n}\n")


def self_test() -> int:
    """Prove the instrument separates a defended invariant from an undefended one.

    This tool decides whether a green suite actually defends its contract, and every
    teeth number in the repo is its verdict. So it has to be shown distinguishing the
    three outcomes on code whose answer is known before the run:

      CAUGHT        real assertion + broken code  -> suite must go red
      SURVIVED      vacuous test  + broken code   -> suite stays green, the hole is real
      BASELINE-RED  the unmutated project already fails -> verdict VOID, not a CAUGHT

    The third is the one that cost four by-hand runs to learn: a red baseline turns every
    mutant red for the wrong reason and reports a fake CAUGHT.
    """
    break_double = lambda text: text.replace("return n * 2", "return n + 2")  # noqa: E731

    cases = [
        ("CAUGHT", _DEFENDED, _IMPL),
        ("SURVIVED", _UNDEFENDED, _IMPL),
        # baseline already red: the test expects 6 from an impl that returns 5
        ("BASELINE-RED", _DEFENDED, "package t\n\nfunc Double(n int) int {\n\treturn n + 2\n}\n"),
    ]
    failures = []
    for want, test_src, impl_src in cases:
        with tempfile.TemporaryDirectory() as td:
            art = Path(td) / "art"
            art.mkdir()
            (art / "go.mod").write_text(_MOD)
            (art / "t.go").write_text(impl_src)
            (art / "t_test.go").write_text(test_src)
            got, note = verdict_for(art, "t.go", break_double)
        if got != want:
            failures.append(f"expected {want}, got {got} ({note})")

    # FOURTH OUTCOME, added after it was observed in the wild: a tree with NO test files.
    # `go test` exits 0 on a package with no _test.go, so the mutant passes and the verdict
    # used to read SURVIVED — "GREEN on broken code — UNDEFENDED" — about an artifact that
    # was never asked anything. Seen live during the corpus rebuild: usersapi-v4 held
    # go.mod and store.go and nothing else, and both its invariants were reported
    # undefended in that window.
    with tempfile.TemporaryDirectory() as td:
        art = Path(td) / "art"
        art.mkdir()
        (art / "go.mod").write_text(_MOD)
        (art / "t.go").write_text(_IMPL)
        got, note = verdict_for(art, "t.go", break_double)
        if got != "NOTESTS":
            failures.append(f"a tree with no _test.go must be NOTESTS, got {got} ({note})")

    # FIFTH OUTCOME, added 29 July: a mutation that produces code the COMPILER rejects.
    # `go test` exits non-zero on a build failure exactly as it does on a failed assertion,
    # so such a mutant used to read CAUGHT — "the invariant is defended" — when the suite
    # never ran at all. Two entries in MUTATIONS do this today (eventbus bus.go, ratelimit
    # middleware.go); their _drop_line patterns cut part of a multi-line statement.
    #
    # The planted mutation below deletes the closing brace, which is the cheapest way to make
    # a file that cannot parse. A DEFENDED test is used deliberately: the point is that the
    # verdict must NOT be CAUGHT even though a real test would have caught a real mutation
    # here — that is exactly the confusion being separated.
    break_syntax = lambda text: text.replace("return n * 2\n}", "return n * 2")  # noqa: E731
    with tempfile.TemporaryDirectory() as td:
        art = Path(td) / "art"
        art.mkdir()
        (art / "go.mod").write_text(_MOD)
        (art / "t.go").write_text(_IMPL)
        (art / "t_test.go").write_text(_DEFENDED)
        got, note = verdict_for(art, "t.go", break_syntax)
        if got != "MUTANT-BROKEN":
            failures.append(f"a mutant the compiler rejects must be MUTANT-BROKEN, not "
                            f"credited to the tests. got {got} ({note})")

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print("OK — a defended invariant is CAUGHT, a vacuous one SURVIVES, a red baseline "
          "voids the verdict, a tree with no tests is NOTESTS rather than undefended, and a "
          "mutant the compiler REJECTS is MUTANT-BROKEN rather than credited to the tests")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    # The scoreboard reads every registered artifact, so a live generation makes it
    # unreproducible at best and wrong at worst — this is the run that reported two
    # usersapi invariants UNDEFENDED from a tree with no test files.
    from _corpus_state import check as _corpus_check
    _corpus_check()
    wanted = set(sys.argv[1:])
    rows = [m for m in MUTATIONS if not wanted or m[0] in wanted]
    # ZERO SELECTED MUTATIONS IS AN ERROR, NOT A GREEN RUN. This is the teeth suite: its
    # headline is "29 CAUGHT / 0 SURVIVED", and a typo'd name produced "0 probes, 0
    # SURVIVED" — which summarises to the same reassuring shape. The one number a teeth
    # report must never lose is how many mutations it actually ran.
    if wanted and not rows:
        known = ", ".join(sorted({m[0] for m in MUTATIONS}))
        raise SystemExit(f"no registered mutation matches {', '.join(sorted(wanted))}\n"
                         f"known specs: {known}")
    print(f"{'spec':<12} {'verdict':<9} invariant")
    print("-" * 74)
    undef = void = 0
    verdicts = []
    for spec, rel, desc, mut in rows:
        verdict, note = _run(spec, rel, desc, mut)
        verdicts.append(verdict)
        if verdict == "SURVIVED":
            undef += 1
        elif verdict == "BASELINE-RED":
            void += 1
        mark = {"CAUGHT": "✓", "SURVIVED": "✗ UNDEFENDED", "BASELINE-RED": "✗ BASELINE-RED",
                "NOAPPLY": "· n/a", "SKIP": "· skip",
                "NOTESTS": "· no tests"}.get(verdict, verdict)
        print(f"{spec:<12} {mark:<9} {desc}")
        if verdict in ("NOAPPLY", "SKIP", "BASELINE-RED", "NOTESTS"):
            print(f"{'':<12} {'':<9} ({note})")
    print("-" * 74)
    # Count what DID NOT RUN alongside what failed. Every row already prints its own
    # NOAPPLY note, but the summary line is what gets quoted, and "0 invariant(s)
    # UNDEFENDED" is what a suite where NOTHING APPLIED prints too.
    noapply = sum(1 for r in verdicts if r in ("NOAPPLY", "SKIP", "NOTESTS"))
    print(f"{undef} invariant(s) UNDEFENDED (suite green on broken code); "
          f"{len(verdicts) - noapply}/{len(verdicts)} mutation(s) actually ran.")
    if void:
        print(f"{void} entr(y/ies) VOID — unmutated baseline already red (verdict untrustworthy).")
    print("SURVIVED = coverage cannot see it; a test never written lowers no number.")
    # A selection where NOTHING ran is a failed run, not a clean one.
    return 1 if (undef or void or (verdicts and noapply == len(verdicts))) else 0


if __name__ == "__main__":
    raise SystemExit(main())
