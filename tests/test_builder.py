"""Offline unit tests for the GuildLM Builder.

No network and no model are used. The GoToolchain tests DO invoke the real local
`go` binary (that is the whole point — the compile/test feedback must be real).
"""

from __future__ import annotations

import shutil

import pytest

from src.builder import (
    FakeCoder,
    FileSpec,
    FileTask,
    GoToolchain,
    Spec,
    build,
    extract_code,
    plan,
)

GO = shutil.which("go")
requires_go = pytest.mark.skipif(GO is None, reason="go toolchain not installed")


# --------------------------------------------------------------------------- #
# extract_code
# --------------------------------------------------------------------------- #


def test_extract_code_go_fence():
    out = "Here is the file:\n```go\npackage main\n\nfunc main() {}\n```\nDone!"
    assert extract_code(out) == "package main\n\nfunc main() {}\n"


def test_extract_code_bare_golang_fence():
    out = "```golang\npackage main\n```"
    assert extract_code(out) == "package main\n"


def test_extract_code_no_fence_returns_whole_text():
    out = "package main\n\nfunc main() {}"
    assert extract_code(out) == "package main\n\nfunc main() {}\n"


def test_extract_code_first_block_wins():
    out = "```go\nfirst\n```\nblah\n```go\nsecond\n```"
    assert extract_code(out) == "first\n"


def test_extract_code_mod_fence():
    out = "```mod\nmodule x\n\ngo 1.23\n```"
    assert extract_code(out) == "module x\n\ngo 1.23\n"


# --------------------------------------------------------------------------- #
# Spec & plan
# --------------------------------------------------------------------------- #


def _sample_spec() -> Spec:
    return Spec(
        name="demo",
        description="a demo",
        go_module="example.com/demo",
        files=(
            FileSpec(path="go.mod", purpose="module file"),
            FileSpec(path="main.go", purpose="entrypoint"),
        ),
    )


def test_plan_preserves_order_and_indices():
    tasks = plan(_sample_spec())
    assert [t.spec.path for t in tasks] == ["go.mod", "main.go"]
    assert [t.index for t in tasks] == [0, 1]
    assert all(isinstance(t, FileTask) for t in tasks)


def test_spec_from_dict():
    spec = Spec.from_dict(
        {
            "name": "demo",
            "description": "d",
            "go_module": "example.com/demo",
            "files": [{"path": "go.mod", "purpose": "p"}],
        }
    )
    assert spec.name == "demo"
    assert spec.language == "go"
    assert spec.files[0].path == "go.mod"


def test_spec_from_yaml(tmp_path):
    yaml_text = (
        "name: demo\n"
        "description: d\n"
        "go_module: example.com/demo\n"
        "files:\n"
        "  - path: go.mod\n"
        "    purpose: module\n"
    )
    p = tmp_path / "spec.yaml"
    p.write_text(yaml_text)
    spec = Spec.from_yaml(p)
    assert spec.files[0].purpose == "module"


# --------------------------------------------------------------------------- #
# GoToolchain against the real `go` binary
# --------------------------------------------------------------------------- #

GO_MOD = "module example.com/demo\n\ngo 1.23\n"
GOOD_GO = "package main\n\nfunc main() {\n\tprintln(\"ok\")\n}\n"
# `x` is declared and not used -> a real compile error referencing main.go.
BAD_GO = "package main\n\nfunc main() {\n\tx := 1\n}\n"


@requires_go
def test_toolchain_good_snippet(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD)
    (tmp_path / "main.go").write_text(GOOD_GO)
    ok, output = GoToolchain().check(tmp_path)
    assert ok, output


@requires_go
def test_toolchain_bad_snippet(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD)
    (tmp_path / "main.go").write_text(BAD_GO)
    ok, output = GoToolchain().build(tmp_path)
    assert not ok
    assert "main.go" in output


# --------------------------------------------------------------------------- #
# The build() loop end-to-end with FakeCoder + real go
# --------------------------------------------------------------------------- #


@requires_go
def test_build_loop_converges_to_green(tmp_path):
    spec = _sample_spec()

    # go.mod is correct from the start. main.go is broken on the first pass and
    # correct on the fix round -> the loop must converge.
    coder = FakeCoder(
        {
            "go.mod": [f"```mod\n{GO_MOD}```"],
            "main.go": [
                f"```go\n{BAD_GO}```",  # generation pass: broken
                f"```go\n{GOOD_GO}```",  # fix round: good
            ],
        }
    )

    ok, files = build(spec, coder, tmp_path, max_fix_rounds=4)

    assert ok, "loop should converge to a green build"
    assert (tmp_path / "main.go").read_text() == GOOD_GO
    assert set(files) == {"go.mod", "main.go"}
    # main.go was generated once, then fixed once.
    assert coder.calls.count("main.go") == 2


@requires_go
def test_build_loop_gives_up_when_unfixable(tmp_path):
    spec = _sample_spec()
    coder = FakeCoder(
        {
            "go.mod": [f"```mod\n{GO_MOD}```"],
            "main.go": [f"```go\n{BAD_GO}```"],  # always broken
        }
    )
    ok, _ = build(spec, coder, tmp_path, max_fix_rounds=2)
    assert not ok
