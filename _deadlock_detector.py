#!/usr/bin/env python3
"""Static detector for intra-method self-deadlock on a sync.Mutex/RWMutex.

Why this exists: shortener 2026-07-17 produced Resolve() = RLock(); defer
RUnlock(); ...; Lock(). A read lock cannot be upgraded to a write lock on the
same RWMutex, so it blocks forever — a test TIMEOUT, never a compile error.
mutex_rule fires on the file and an A/B (mutex-intra, refuted) showed the model
writes it even when the prompt names the exact shape. Prompt wording does not
reach it; the model's prior (RLock the read half, Lock the write half) wins.

But the defect is decidable FROM THE FILE ALONE, which by this project's own
rule (self_dropped_decls) is what belongs in a check rather than a prompt: if a
method DEFERS the unlock of a mutex M — so M is held until the function returns —
and then acquires M AGAIN anywhere after that defer, the second acquire is nested
inside the first and deadlocks unconditionally. No spec, no purpose, no call
graph.

Soundness is the whole point — a gate that rejects correct code is worse than no
gate. This flags ONLY the deferred-then-reacquired shape, which cannot be
anything but a deadlock. It does NOT attempt the cross-method case (that needs a
call graph and is mutex_rule's domain), and it does NOT flag Lock/Unlock/Lock
sequential code (no defer holding the first).
"""
from __future__ import annotations

import re

# `s.mu`, `m.lock`, `r.mu` — the receiver chain before the lock call. Group 1 is
# the mutex expression; group 2 is which primitive.
_LOCK_RE = re.compile(r"\b([A-Za-z_]\w*(?:\.\w+)*)\.(RLock|Lock)\(\)")
_DEFER_UNLOCK_RE = re.compile(r"\bdefer\s+([A-Za-z_]\w*(?:\.\w+)*)\.(RUnlock|Unlock)\(\)")
# Start of a func or method. We brace-match its body ourselves.
_FUNC_RE = re.compile(r"\bfunc\b[^{;]*\{", re.S)


def _method_name(header: str) -> str:
    """A readable label for the log: the method/func name from its header."""
    m = re.search(r"\)\s*([A-Za-z_]\w*)\s*\(", header)  # func (recv) Name(
    if m:
        return m.group(1)
    m = re.search(r"\bfunc\s+([A-Za-z_]\w*)\s*\(", header)  # func Name(
    return m.group(1) if m else "func"


def _bodies(code: str):
    """Yield (name, body_text) for each top-level func/method by brace matching."""
    for fm in _FUNC_RE.finditer(code):
        header = code[fm.start():fm.end()]
        depth, i, n = 1, fm.end(), len(code)
        while i < n and depth:
            c = code[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        yield _method_name(header), code[fm.end():i - 1]


def mutex_self_deadlock(code: str) -> set[str]:
    """Names of methods that acquire a mutex again after deferring its unlock.

    Each such method holds the first lock to function return (the defer) and then
    re-acquires the SAME mutex — a nested acquire on a non-reentrant lock, which
    deadlocks. Returns the empty set for clean code.
    """
    bad: set[str] = set()
    for name, body in _bodies(code):
        # For every deferred unlock, does the SAME mutex get acquired after it?
        for dm in _DEFER_UNLOCK_RE.finditer(body):
            mutex = dm.group(1)
            after = body[dm.end():]
            for lk in _LOCK_RE.finditer(after):
                if lk.group(1) == mutex:
                    bad.add(name)
                    break
    return bad


if __name__ == "__main__":
    import sys
    for path in sys.argv[1:]:
        try:
            hits = mutex_self_deadlock(open(path).read())
        except OSError as e:
            print(f"{path}: {e}")
            continue
        print(f"{path}: {'DEADLOCK ' + ', '.join(sorted(hits)) if hits else 'clean'}")
