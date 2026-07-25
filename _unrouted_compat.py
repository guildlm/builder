"""Did a fix-loop change alter UNROUTED builds? Answer by diffing, not by reading.

Every routing change so far has claimed the same guarantee — "inert without --fleet" —
and the guarantee is easy to assert and easy to get subtly wrong, because the fleet
code sits INSIDE the loop every build runs. This makes the claim falsifiable: it runs
one deterministic build (FakeCoder + real go, no model, no network) and dumps
everything an unrouted build can be judged by — the verdict, every generated file, and
the ordered sequence of files the coder was asked to produce — as canonical JSON.

Run it in two trees and diff. Same bytes, same build:

    git worktree add /tmp/builder-pre <commit-before>
    cp _unrouted_compat.py /tmp/builder-pre/
    (cd /tmp/builder-pre && python _unrouted_compat.py > /tmp/pre.json)
    python _unrouted_compat.py > /tmp/post.json
    diff /tmp/pre.json /tmp/post.json

The fixture deliberately STALLS and WIDENS (a test asserting a wrong value, which no
deterministic gate guesses, so the loop runs its whole budget and the package impl is
widened into the fix targets from round two). Widening is where the fleet logic lives,
so a fixture that converges on the first round would compare nothing.

Result on record (logs/FINDING-escalation-granularity.txt): 12a497d vs the
blamed-only escalation rule — identical, sha256 c9a90be7…
"""
from __future__ import annotations

import hashlib
import io
import contextlib
import json
import sys
import tempfile
import pathlib

from src.builder import FakeCoder, FileSpec, Spec, build

GO_MOD = "module example.com/demo\n\ngo 1.23\n"
IMPL = "package main\n\nfunc Add(a, b int) int {\n\treturn a + b\n}\n\nfunc main() {}\n"
# Compiles and runs; the assertion is simply wrong, so the loop keeps failing at
# RUNTIME -> the package impl gets widened into the fix targets after two rounds.
TEST = ("package main\n\nimport \"testing\"\n\n"
        "func TestAdd(t *testing.T) {\n\tif Add(1, 2) != 4 {\n\t\tt.Fatalf(\"boom\")\n\t}\n}\n")

spec = Spec(
    name="demo", description="a demo", go_module="example.com/demo",
    files=(
        FileSpec(path="go.mod", purpose="module file"),
        FileSpec(path="mathx.go", purpose="Add returns a+b; main is empty"),
        FileSpec(path="mathx_test.go", purpose="tests Add"),
    ),
)
coder = FakeCoder({
    "go.mod": [f"```mod\n{GO_MOD}```"],
    "mathx.go": [f"```go\n{IMPL}```"],
    "mathx_test.go": [f"```go\n{TEST}```"],
})

with tempfile.TemporaryDirectory() as tmp:
    out = pathlib.Path(tmp) / "proj"
    with contextlib.redirect_stderr(io.StringIO()):
        ok, files = build(spec, coder, out, max_fix_rounds=5)
    dump = {
        "ok": ok,
        "files": {p: (out / p).read_text() for p in sorted(files)},
        "call_sequence": coder.calls,
    }

blob = json.dumps(dump, sort_keys=True, indent=1)
print(blob)
print("SHA256", hashlib.sha256(blob.encode()).hexdigest(), file=sys.stderr)
