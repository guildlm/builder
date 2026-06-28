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
    _fix_prompt,
    _generate_prompt,
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


# --------------------------------------------------------------------------- #
# Prompt construction — guards against the multi-file "redeclared" failure
# where the coder pastes copies of functions that already exist in the package.
# --------------------------------------------------------------------------- #


def _impl_task() -> FileTask:
    return FileTask(index=1, spec=FileSpec(path="stringkit_test.go", purpose="tests"))


def test_generate_prompt_warns_against_redeclaring_when_context_exists():
    spec = _sample_spec()
    written = {"stringkit.go": "package stringkit\n\nfunc Reverse(s string) string { return s }\n"}
    prompt = _generate_prompt(spec, _impl_task(), written)
    # The already-written file is shown AND the no-redeclare rule is present.
    assert "func Reverse" in prompt
    assert "redeclared in this block" in prompt
    assert "do not paste copies" in prompt.lower() or "do not redeclare" in prompt.lower()


def test_generate_prompt_omits_reuse_rule_on_first_file():
    spec = _sample_spec()
    prompt = _generate_prompt(spec, FileTask(index=0, spec=spec.files[0]), {})
    # Nothing written yet -> no reuse rule (it would be noise / nonsense).
    assert "redeclared in this block" not in prompt


def test_fix_prompt_includes_sibling_files_for_redeclaration_context():
    written = {
        "stringkit.go": "package stringkit\n\nfunc Reverse(s string) string { return s }\n",
        "stringkit_test.go": "package stringkit\n// (buggy: redefines Reverse)\n",
    }
    prompt = _fix_prompt(
        _impl_task(),
        written["stringkit_test.go"],
        "./stringkit_test.go:10: Reverse redeclared in this block",
        written,
    )
    # The sibling impl is shown so the fixer can see where Reverse really lives.
    assert "func Reverse" in prompt
    assert "other files in this package" in prompt
    # The sibling block shows stringkit.go but NOT the target itself; the target
    # appears only once, under the "current" heading.
    assert "--- stringkit.go ---" in prompt
    assert "--- stringkit_test.go ---" not in prompt
    assert prompt.count("--- current stringkit_test.go ---") == 1


def test_fix_prompt_without_siblings_is_still_valid():
    prompt = _fix_prompt(_impl_task(), "package stringkit\n", "some error", None)
    assert "other files in this package" not in prompt
    assert "TARGET_FILE: stringkit_test.go" in prompt


def test_generate_prompt_test_file_warns_against_inventing_edge_cases():
    spec = _sample_spec()
    prompt = _generate_prompt(spec, _impl_task(), {})  # path ends _test.go
    assert "TEST file" in prompt
    assert "do not invent edge cases" in prompt


def test_generate_prompt_non_test_file_has_no_test_rule():
    spec = _sample_spec()
    impl = FileTask(index=1, spec=FileSpec(path="stringkit.go", purpose="impl"))
    prompt = _generate_prompt(spec, impl, {})
    assert "do not invent edge cases" not in prompt


def test_fix_prompt_assertion_failure_steers_toward_fixing_the_test():
    err = "--- FAIL: TestIsPalindrome (0.00s)\n    IsPalindrome(\"x\") = true, want false"
    prompt = _fix_prompt(_impl_task(), "package stringkit\n", err, None)
    assert "FAILING TEST ASSERTION" in prompt
    assert "correct the test's expected value" in prompt


def test_fix_prompt_compile_error_has_no_assertion_rule():
    err = "./stringkit_test.go:10: Reverse redeclared in this block"
    prompt = _fix_prompt(_impl_task(), "package stringkit\n", err, None)
    assert "FAILING TEST ASSERTION" not in prompt
