#!/usr/bin/env python3
"""Verify every example in a retrieval corpus actually compiles.

The corpus (``examples/verified_contracts.jsonl``) is the project's highest-
leverage asset: a small model writes a correct, tested backend the moment it's
grounded in a known-good example of the contract it must honour (see Report #6).
That only holds if every example in the corpus is genuinely known-good — a corpus
that silently rots teaches the model to write broken Go.

This script extracts the ```go block from each example's ``response``, drops it
into a throwaway module, and runs the real toolchain:

    go build ./...        for every .go file
    go test ./...         when the file is a _test.go (so test examples are run)

Examples are grouped into one module per ``go_module`` hint, or one module per
example otherwise, so an impl + its test verify together. Pure-stdlib only; no
network, no Docker; $0.

Usage:
    python verify_corpus.py [examples/verified_contracts.jsonl ...]
Exit code is non-zero if any example fails to build/test.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_GO_BLOCK = re.compile(r"```go\s*\n(.*?)```", re.DOTALL)
_PKG = re.compile(r"^package\s+(\w+)", re.MULTILINE)
_TEST_FN = re.compile(r"\bfunc\s+Test\w*\s*\(", re.MULTILINE)


def _extract_go(response: str) -> str | None:
    m = _GO_BLOCK.search(response or "")
    return m.group(1).rstrip() + "\n" if m else None


def _is_test(code: str) -> bool:
    return bool(_TEST_FN.search(code))


def _pkg_name(code: str) -> str:
    m = _PKG.search(code)
    return m.group(1) if m else "main"


def _filename(code: str, idx: int) -> str:
    base = "code" if _pkg_name(code) == "main" else _pkg_name(code)
    return f"{base}_{idx}_test.go" if _is_test(code) else f"{base}_{idx}.go"


def verify_corpus(path: str | Path) -> tuple[int, int, list[str]]:
    """Return (passed, total, failures). Each example is grouped with siblings
    that share its package name so an impl and its test compile together."""
    examples: list[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            code = _extract_go(json.loads(line).get("response", ""))
            if code:
                examples.append(code)

    # Group by ORDER, not package name: each non-test example starts a new module
    # and any following test example(s) join it. The corpus is authored impl-then-
    # its-test, so this pairs an impl with its test while keeping distinct programs
    # (two different `package main` services) in separate modules — otherwise they
    # collide on redeclared main/newMux.
    groups: list[list[str]] = []
    for code in examples:
        if _is_test(code) and groups:
            groups[-1].append(code)
        else:
            groups.append([code])

    passed = 0
    failures: list[str] = []
    for gi, codes in enumerate(groups):
        pkg = _pkg_name(codes[0])
        with tempfile.TemporaryDirectory() as d:
            mod = Path(d)
            (mod / "go.mod").write_text(f"module verify/{pkg}{gi}\n\ngo 1.23\n")
            has_test = False
            for i, code in enumerate(codes):
                (mod / _filename(code, i)).write_text(code)
                has_test = has_test or _is_test(code)
            ok, out = _run(["build", "./..."], mod)
            if ok and has_test:
                ok, out = _run(["test", "./..."], mod)
            if ok:
                passed += len(codes)
            else:
                tail = out.strip().splitlines()[-1] if out.strip() else "failed"
                failures.append(f"group {gi} (package {pkg}): {tail}")
    return passed, len(examples), failures


def _run(args: list[str], cwd: Path) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["go", *args], cwd=str(cwd), capture_output=True, text=True, timeout=180
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def main(argv: list[str]) -> int:
    paths = argv[1:] or ["examples/verified_contracts.jsonl"]
    bad = 0
    for p in paths:
        passed, total, failures = verify_corpus(p)
        status = "✓" if not failures else "✗"
        print(f"{status} {p}: {passed}/{total} examples build/test clean")
        for f in failures:
            print(f"    ✗ {f}")
        bad += len(failures)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
