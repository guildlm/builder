#!/usr/bin/env python3
"""Project-level benchmark — the REAL "world's best Go model" metric.

Unit benchmarks score toy functions. This scores the guild on what actually
matters: can it MAINTAIN, TEST, and REVIEW whole multi-file Go projects with the
real toolchain as judge. Runs over the verified projects in guild-code/go/projects.

  MAINTAIN: copy the green base project, apply its change request via the Builder's
            maintain() loop, score 1 iff the project is still green AND changed.
  REVIEW:   feed the project's buggy variant to the review model; score 1 iff the
            response mentions any of the bug's keywords (same rule as go_review_bench).
  TEST:     strip the project's tests, ask the test model to write a new test for
            the package; score 1 iff it compiles, asserts, and passes on the
            (correct) implementation.

Usage:
  python project_bench.py --projects ../guild-code/go/projects \
      --base-url http://localhost:8080/v1 --model M \
      --test-base-url http://localhost:8081/v1 --test-model M \
      --review-base-url http://localhost:8082/v1 --review-model M \
      --capabilities maintain,review,test
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.builder import (  # noqa: E402
    GoToolchain, OpenAICoder, maintain, has_assertions, extract_code,
)

_ASSERT = re.compile(r"\bt\.(Error|Errorf|Fatal|Fatalf)\b")


def _load(projects_dir: Path) -> list[dict]:
    manifest = json.loads((projects_dir / "manifest.json").read_text())
    out = []
    for m in manifest:
        d = projects_dir / m["name"]
        task = json.loads((d / "task.json").read_text())
        out.append({"dir": d, "task": task})
    return out


def _copy_project(src: Path, dst: Path) -> None:
    for p in src.rglob("*"):
        if p.is_file() and (p.suffix == ".go" or p.name == "go.mod"):
            q = dst / p.relative_to(src)
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_text(p.read_text(encoding="utf-8"))


def bench_maintain(proj, dev_coder, toolchain, candidates, max_fix_rounds) -> bool:
    req = proj["task"]["maintain"]["request"]
    if not req:
        return False
    with tempfile.TemporaryDirectory() as d:
        _copy_project(proj["dir"], Path(d))
        before = {p.name: p.read_text() for p in Path(d).rglob("*.go")}
        ok, _ = maintain(d, req, dev_coder, max_fix_rounds=max_fix_rounds, candidates=candidates)
        if not ok:
            return False
        after = {p.name: p.read_text() for p in Path(d).rglob("*.go")}
        changed = after != before
        green, _ = toolchain.check(d)
        return bool(green and changed)


def bench_review(proj, review_coder) -> bool:
    rv = proj["task"]["review"]
    kws = [k.lower() for k in rv.get("keywords", [])]
    buggy = rv.get("path", "")
    # the buggy content lives in task.json's review only as bug+keywords; the
    # buggy file content was saved into teaching, so re-read from the project's
    # review content if present. Fall back: review the named file from the base.
    code = rv.get("content")
    if not code:
        f = proj["dir"] / buggy
        code = f.read_text() if f.exists() else ""
    if not code or not kws:
        return False
    prompt = (
        "Review this Go code and identify the real bug. Explain what is wrong.\n\n"
        f"```go\n{code}\n```"
    )
    out = review_coder.generate(prompt).lower()
    return any(k in out for k in kws)


def bench_test(proj, test_coder, toolchain) -> bool:
    with tempfile.TemporaryDirectory() as d:
        dd = Path(d)
        # copy impl only (strip existing tests)
        for p in proj["dir"].rglob("*"):
            if p.is_file() and (p.name == "go.mod" or (p.suffix == ".go" and not p.name.endswith("_test.go"))):
                q = dd / p.relative_to(proj["dir"])
                q.parent.mkdir(parents=True, exist_ok=True)
                q.write_text(p.read_text())
        # pick the package name from any impl file
        pkg = "main"
        for p in dd.rglob("*.go"):
            m = re.search(r"^package\s+(\w+)", p.read_text(), re.MULTILINE)
            if m:
                pkg = m.group(1)
                break
        listing = "".join(f"--- {p.relative_to(dd)} ---\n{p.read_text()}\n" for p in sorted(dd.rglob("*.go")))
        prompt = (
            f"Write a thorough table-driven Go test (package {pkg}) for this project. "
            f"Cover the exported behaviour and edge cases with real t.Error/t.Fatal "
            f"assertions. Standard library only.\n\n{listing}\n"
            f"Output one complete _test.go file as a single ```go block."
        )
        test_code = extract_code(test_coder.generate(prompt))
        if not _ASSERT.search(test_code):
            return False
        (dd / "guild_bench_test.go").write_text(test_code)
        green, _ = toolchain.check(dd)
        return bool(green)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", default="../guild-code/go/projects")
    ap.add_argument("--model", default=None)
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--test-model", default=None)
    ap.add_argument("--test-base-url", default=None)
    ap.add_argument("--review-model", default=None)
    ap.add_argument("--review-base-url", default=None)
    ap.add_argument("--candidates", type=int, default=2)
    ap.add_argument("--max-fix-rounds", type=int, default=4)
    ap.add_argument("--capabilities", default="maintain,review,test")
    args = ap.parse_args(argv[1:])

    caps = set(args.capabilities.split(","))
    toolchain = GoToolchain()
    dev = OpenAICoder(model=args.model, base_url=args.base_url)
    test = OpenAICoder(model=args.test_model or args.model, base_url=args.test_base_url or args.base_url)
    review = OpenAICoder(model=args.review_model or args.model, base_url=args.review_base_url or args.base_url)

    projects = _load(Path(args.projects).resolve())
    print(f"project_bench: {len(projects)} projects | capabilities={sorted(caps)}\n")

    score = {"maintain": 0, "review": 0, "test": 0}
    for proj in projects:
        name = proj["task"]["name"]
        row = []
        if "maintain" in caps:
            ok = bench_maintain(proj, dev, toolchain, args.candidates, args.max_fix_rounds)
            score["maintain"] += ok
            row.append(("+" if ok else "-") + "maintain")
        if "review" in caps:
            ok = bench_review(proj, review)
            score["review"] += ok
            row.append(("+" if ok else "-") + "review")
        if "test" in caps:
            ok = bench_test(proj, test, toolchain)
            score["test"] += ok
            row.append(("+" if ok else "-") + "test")
        print(f"  {name:28s} {' '.join(row)}")

    n = len(projects)
    print()
    for cap in ("maintain", "review", "test"):
        if cap in caps:
            print(f"{cap:9s}: {score[cap]}/{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
