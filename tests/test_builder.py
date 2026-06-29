"""Offline unit tests for the GuildLM Builder.

No network and no model are used. The GoToolchain tests DO invoke the real local
`go` binary (that is the whole point — the compile/test feedback must be real).
"""

from __future__ import annotations

import shutil
import sys

import pytest

from src.builder import (
    FakeCoder,
    FileSpec,
    FileTask,
    GoToolchain,
    RoleRoutingCoder,
    Spec,
    Retriever,
    _fix_prompt,
    _generate_file,
    _generate_prompt,
    _review_pass,
    build,
    extract_code,
    gofmt_code,
    has_assertions,
    nonstdlib_imports,
    plan,
    role_for_path,
    top_level_decls,
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
# Parses cleanly (gofmt-valid) but `go build` fails: undefinedSym is not declared.
# Used to prove verified fix-selection rejects a candidate that merely PARSES.
BAD_PARSES_GO = "package main\n\nfunc main() {\n\tprintln(undefinedSym)\n}\n"


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


def test_fix_prompt_missing_module_demands_stdlib_swap():
    err = (
        "handlers.go:8:2: no required module provides package "
        "golang.org/x/net/http/httpguts; to add it:\n\tgo get golang.org/x/net/..."
    )
    prompt = _fix_prompt(_impl_task(), "package main\n", err, None)
    assert "NOT in the Go standard library" in prompt
    assert "Remove that import" in prompt


def test_fix_prompt_normal_compile_error_has_no_import_rule():
    err = "./stringkit_test.go:10: Reverse redeclared in this block"
    prompt = _fix_prompt(_impl_task(), "package stringkit\n", err, None)
    assert "NOT in the Go standard library" not in prompt


# --------------------------------------------------------------------------- #
# Best-of-N generation (small-model leverage: reject candidates that don't parse)
# --------------------------------------------------------------------------- #


@requires_go
def test_syntax_ok_accepts_valid_rejects_broken():
    tc = GoToolchain()
    assert tc.syntax_ok("package main\n\nfunc main() {}\n")
    assert not tc.syntax_ok("package main\n\nfunc main( {\n")


@requires_go
def test_generate_file_best_of_n_keeps_first_parseable():
    task = FileTask(index=1, spec=FileSpec(path="main.go", purpose="entry"))
    coder = FakeCoder(
        {
            "main.go": [
                "```go\npackage main\n\nfunc main( {\n```",  # broken: won't parse
                "```go\npackage main\n\nfunc main() {}\n```",  # good
            ]
        }
    )
    code = _generate_file(coder, _sample_spec(), task, {}, candidates=2, toolchain=GoToolchain())
    assert "func main() {}" in code
    assert coder.calls.count("main.go") == 2  # it had to draw the second sample


def test_has_assertions():
    real = "package p\nimport \"testing\"\nfunc TestX(t *testing.T){ if 1!=2 { t.Errorf(\"x\") } }\n"
    trivial = "package p\nimport \"testing\"\nfunc TestX(t *testing.T){ _ = 1 }\n"
    assert has_assertions(real)
    assert not has_assertions(trivial)


@requires_go
def test_best_of_n_rejects_trivial_test():
    task = FileTask(index=2, spec=FileSpec(path="x_test.go", purpose="tests"))
    coder = FakeCoder(
        {
            "x_test.go": [
                "```go\npackage p\nimport \"testing\"\nfunc TestX(t *testing.T) { _ = 1 }\n```",  # trivial
                "```go\npackage p\nimport \"testing\"\nfunc TestX(t *testing.T) { if 1 != 1 { t.Fatal(\"x\") } }\n```",  # asserts
            ]
        }
    )
    code = _generate_file(coder, _sample_spec(), task, {}, candidates=2, toolchain=GoToolchain())
    assert "t.Fatal" in code  # kept the asserting candidate
    assert coder.calls.count("x_test.go") == 2


@requires_go
def test_gofmt_code_formats_valid_go():
    ugly = 'package main\nfunc main(){println( "x" )}\n'
    out = gofmt_code(ugly)
    # gofmt tabs the body and tightens the call — a real reformat happened.
    assert "func main() {" in out
    assert out != ugly


@requires_go
def test_gofmt_code_returns_input_when_unparseable():
    broken = "package main\n\nfunc main( {\n"  # syntax error
    assert gofmt_code(broken) == broken


@requires_go
def test_verified_contracts_corpus_actually_compiles():
    """The retrieval corpus is the project's highest-leverage asset (Report #6) —
    a rotten example teaches the model to write broken Go. Guard it: every example
    in examples/verified_contracts.jsonl must build (and, if a test, pass)."""
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    corpus = root / "examples" / "verified_contracts.jsonl"
    if not corpus.exists():
        pytest.skip("no verified_contracts.jsonl yet")
    proc = subprocess.run(
        [sys.executable, "verify_corpus.py", str(corpus)],
        cwd=str(root), capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_gofmt_code_removes_unused_import_when_goimports_available():
    # The single most common small-model failure: a dead import that blocks the
    # whole compile. goimports prunes it deterministically, no model fix-round.
    from src.builder import _goimports_bin

    if _goimports_bin() is None:
        pytest.skip("goimports not installed")
    src = (
        'package x\n\nimport (\n\t"testing"\n\t"unicode"\n)\n\n'
        'func TestA(t *testing.T) {\n\tif 1 != 1 {\n\t\tt.Fatal("x")\n\t}\n}\n'
    )
    out = gofmt_code(src)
    assert '"unicode"' not in out  # the dead import is pruned
    assert '"testing"' in out  # the used import is kept


@requires_go
def test_verified_fix_selection_prefers_green_candidate(tmp_path):
    """Fix loop with candidates>1: a repair that merely PARSES but still fails
    `go build` must lose to a later candidate that actually goes green. Parse-only
    best-of-N would have kept the first (parsing-but-broken) candidate."""
    spec = _sample_spec()
    coder = FakeCoder(
        {
            "go.mod": [f"```mod\n{GO_MOD}```"],
            "main.go": [
                f"```go\n{BAD_GO}```",  # generation: unused var -> build fails
                f"```go\n{BAD_PARSES_GO}```",  # fix cand 1: parses, undefined sym -> build fails
                f"```go\n{GOOD_GO}```",  # fix cand 2: green
            ],
        }
    )
    ok, _files = build(spec, coder, tmp_path, max_fix_rounds=2, candidates=2)
    assert ok, "loop should converge using the green candidate"
    assert (tmp_path / "main.go").read_text() == GOOD_GO  # the green candidate won
    # main.go: 1 generation call + 2 fix candidates sampled in round 1.
    assert coder.calls.count("main.go") == 3


def test_nonstdlib_imports_detects_third_party():
    block = (
        "package main\n\nimport (\n\t\"fmt\"\n\t\"net/http\"\n"
        "\t\"github.com/gorilla/mux\"\n)\n"
    )
    assert nonstdlib_imports(block) == ["github.com/gorilla/mux"]
    single = 'package main\n\nimport "golang.org/x/net/http/httpguts"\n'
    assert nonstdlib_imports(single) == ["golang.org/x/net/http/httpguts"]
    stdlib = "package main\n\nimport (\n\t\"fmt\"\n\t\"encoding/json\"\n)\n"
    assert nonstdlib_imports(stdlib) == []


def test_top_level_decls_extracts_package_symbols():
    code = (
        "package main\n\n"
        "import \"fmt\"\n\n"
        "type Task struct{ ID int }\n"
        "type Store struct{}\n\n"
        "var ErrSingle = fmt.Errorf(\"x\")\n\n"
        "var (\n\tErrInvalidTask = fmt.Errorf(\"a\")\n\tErrNotFound = fmt.Errorf(\"b\")\n)\n\n"
        "const Limit = 10\n\n"
        "func NewStore() *Store { return &Store{} }\n"
        "func (s *Store) Get() {}\n"  # method: NOT a top-level name
    )
    decls = top_level_decls(code)
    assert {"Task", "Store", "ErrSingle", "ErrInvalidTask", "ErrNotFound", "Limit", "NewStore"} <= decls
    assert "Get" not in decls  # methods are owned by their type, not redeclared


@requires_go
def test_best_of_n_rejects_redeclaring_candidate():
    # store.go already defines Store/NewStore; the candidate for main.go must not
    # redeclare them (the multi-file collapse).
    task = FileTask(index=1, spec=FileSpec(path="main.go", purpose="entry"))
    written = {"store.go": "package main\n\ntype Store struct{}\n\nfunc NewStore() *Store { return &Store{} }\n"}
    sibling_decls = set()
    from src.builder import top_level_decls as tld
    for c in written.values():
        sibling_decls |= tld(c)
    coder = FakeCoder(
        {
            "main.go": [
                # collapses: redeclares Store + NewStore
                "```go\npackage main\n\ntype Store struct{}\n\nfunc NewStore() *Store { return &Store{} }\n\nfunc main() {}\n```",
                # clean: just main, references the existing Store
                "```go\npackage main\n\nfunc main() { _ = NewStore() }\n```",
            ]
        }
    )
    from src.builder import _sample_clean
    code = _sample_clean(coder, "TARGET_FILE: main.go\n", True, 2, GoToolchain(), "gen", sibling_decls)
    assert "type Store struct" not in code  # rejected the collapsing candidate
    assert "func main()" in code


@requires_go
def test_best_of_n_rejects_nonstdlib_candidate():
    task = FileTask(index=1, spec=FileSpec(path="main.go", purpose="entry"))
    coder = FakeCoder(
        {
            "main.go": [
                '```go\npackage main\nimport "github.com/gorilla/mux"\nvar _ = mux.NewRouter\n```',
                "```go\npackage main\n\nimport \"net/http\"\n\nvar _ = http.NewServeMux\n```",
            ]
        }
    )
    code = _generate_file(coder, _sample_spec(), task, {}, candidates=2, toolchain=GoToolchain())
    assert "net/http" in code and "gorilla/mux" not in code
    assert coder.calls.count("main.go") == 2


def test_generate_file_non_go_is_single_shot():
    # go.mod isn't .go -> no syntax gate, first sample is used even with candidates=3.
    task = FileTask(index=0, spec=FileSpec(path="go.mod", purpose="mod"))
    coder = FakeCoder({"go.mod": ["```mod\nmodule x\n\ngo 1.23\n```"]})
    code = _generate_file(coder, _sample_spec(), task, {}, candidates=3, toolchain=GoToolchain())
    assert "module x" in code
    assert coder.calls.count("go.mod") == 1


# --------------------------------------------------------------------------- #
# Role routing — the guild splits work between dev and test specialists
# --------------------------------------------------------------------------- #


def test_role_for_path():
    assert role_for_path("store.go") == "dev"
    assert role_for_path("main.go") == "dev"
    assert role_for_path("go.mod") == "dev"
    assert role_for_path("store_test.go") == "test"
    assert role_for_path("handlers_test.go") == "test"


class _TagCoder:
    """Minimal Coder that returns its own tag, to prove which one was called."""

    def __init__(self, tag):
        self.tag = tag
        self.seen = []

    def generate(self, prompt):
        self.seen.append(prompt)
        return self.tag


def test_role_routing_dispatches_test_files_to_test_specialist():
    dev, test = _TagCoder("DEV"), _TagCoder("TEST")
    coder = RoleRoutingCoder({"dev": dev, "test": test})
    assert coder.generate("TARGET_FILE: store.go\n...") == "DEV"
    assert coder.generate("TARGET_FILE: store_test.go\n...") == "TEST"
    assert coder.generate("TARGET_FILE: go.mod\n...") == "DEV"


def test_role_routing_falls_back_to_default_when_role_absent():
    dev = _TagCoder("DEV")
    coder = RoleRoutingCoder({"dev": dev})  # no test specialist registered
    assert coder.generate("TARGET_FILE: store_test.go\n...") == "DEV"


# --------------------------------------------------------------------------- #
# Review pass — the reviewer catches bugs that survive a green build,
# and may only help (non-regressing).
# --------------------------------------------------------------------------- #


def _val_spec(desc: str) -> Spec:
    return Spec(
        name="demo",
        description=desc,
        go_module="example.com/demo",
        files=(FileSpec(path="go.mod", purpose="module"), FileSpec(path="main.go", purpose="impl")),
    )


@requires_go
def test_review_pass_applies_non_regressing_fix(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD)
    buggy = "package main\n\nfunc Val() int { return 0 }\n\nfunc main() { _ = Val() }\n"
    (tmp_path / "main.go").write_text(buggy)
    spec = _val_spec("Val() must return 1")
    written = {"go.mod": GO_MOD, "main.go": buggy}
    fixed = "package main\n\nfunc Val() int { return 1 }\n\nfunc main() { _ = Val() }\n"
    reviewer = FakeCoder({"main.go": [f"```go\n{fixed}```"]})

    _review_pass(spec, plan(spec), written, tmp_path, GoToolchain(), reviewer, rounds=1)

    assert "return 1" in written["main.go"]  # the fix stuck (still green)


@requires_go
def test_review_pass_reverts_regressing_edit(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD)
    (tmp_path / "main.go").write_text(GOOD_GO)
    spec = _val_spec("prints ok")
    written = {"go.mod": GO_MOD, "main.go": GOOD_GO}
    reviewer = FakeCoder({"main.go": ["```go\npackage main\n\nfunc main( {\n```"]})  # breaks build

    _review_pass(spec, plan(spec), written, tmp_path, GoToolchain(), reviewer, rounds=1)

    assert written["main.go"] == GOOD_GO  # regression rejected
    assert (tmp_path / "main.go").read_text() == GOOD_GO  # file on disk reverted too


@requires_go
def test_review_pass_clean_leaves_file_untouched(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD)
    (tmp_path / "main.go").write_text(GOOD_GO)
    spec = _val_spec("prints ok")
    written = {"go.mod": GO_MOD, "main.go": GOOD_GO}
    reviewer = FakeCoder({"main.go": ["CLEAN"]})

    _review_pass(spec, plan(spec), written, tmp_path, GoToolchain(), reviewer, rounds=1)

    assert written["main.go"] == GOOD_GO


# --------------------------------------------------------------------------- #
# Retrieval — ground the small model in similar verified examples
# --------------------------------------------------------------------------- #


def _corpus():
    return Retriever(
        [
            ("Write a Go function to reverse a string by runes", "package p\nfunc Rev(s string) string { return s }\n"),
            ("Write a Go HTTP server with net/http", "package p\n// http server\n"),
            ("Write a Go function to sort integers ascending", "package p\nimport \"sort\"\n"),
        ]
    )


def test_retriever_ranks_most_similar_first():
    hits = _corpus().top_k("reverse a string by runes in Go", 2)
    assert hits
    assert "Rev" in hits[0][1]  # the reverse example ranks top


def test_retriever_empty_query_or_zero_k():
    c = _corpus()
    assert c.top_k("", 3) == []
    assert c.top_k("anything", 0) == []


def test_retriever_from_jsonl(tmp_path):
    p = tmp_path / "ex.jsonl"
    p.write_text(
        '{"instruction": "reverse a string", "response": "package p\\nfunc Rev() {}\\n"}\n'
        "\n"  # blank line tolerated
        '{"instruction": "", "response": "skip me"}\n'  # no instruction -> skipped
    )
    r = Retriever.from_jsonl(p)
    hits = r.top_k("reverse a string", 5)
    assert len(hits) == 1 and "Rev" in hits[0][1]


def test_retrieval_block_injected_into_prompt():
    spec = _sample_spec()
    task = FileTask(index=1, spec=FileSpec(path="main.go", purpose="entry"))
    shots = [("reverse a string", "package p\nfunc Rev() {}\n")]
    prompt = _generate_prompt(spec, task, {}, shots=shots)
    assert "Similar verified Go examples" in prompt
    assert "func Rev()" in prompt
    # no shots -> no block
    assert "Similar verified Go examples" not in _generate_prompt(spec, task, {})
