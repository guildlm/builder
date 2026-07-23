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
    FleetCoder,
    FileSpec,
    FileTask,
    GoToolchain,
    RoleRoutingCoder,
    Spec,
    Retriever,
    _canonical_toolchain_output,
    _fix_prompt,
    _is_clean,
    _resample_temperature,
    _sample_clean,
    _test_rule,
    restore_dropped_decls,
    why_dirty,
    self_dropped_decls,
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
    rule_disabled,
    rule_enabled,
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


@requires_go
def test_fleet_escalates_to_a_member_that_can_fix_it(tmp_path):
    """A file the base member can NEVER fix converges once escalation hands it to a
    member that can — the end-to-end payoff of the ensemble finding. base is broken on
    every call; the specialist writes good Go. With _FLEET_ESCALATE_AFTER=2, main.go is a
    target for 2 fix rounds under base, then escalates and the specialist greens it."""
    spec = _sample_spec()
    base = FakeCoder({"go.mod": [f"```mod\n{GO_MOD}```"], "main.go": [f"```go\n{BAD_GO}```"]})
    specialist = FakeCoder({"go.mod": [f"```mod\n{GO_MOD}```"],
                            "main.go": [f"```go\n{GOOD_GO}```"]})
    fleet = FleetCoder([base, specialist])

    ok, files = build(spec, fleet, tmp_path, max_fix_rounds=5)

    assert ok, "escalation to the specialist should green the build"
    assert (tmp_path / "main.go").read_text() == GOOD_GO
    assert fleet.member_for("main.go") == 1, "main.go should have escalated to the specialist"
    # base was tried (generation + fix rounds) before the specialist ever fixed it
    assert base.calls.count("main.go") >= 2
    assert specialist.calls.count("main.go") >= 1


@requires_go
def test_fleet_of_one_is_identical_to_the_bare_coder(tmp_path):
    """A single-member fleet must converge exactly like the coder alone (no escalation
    path taken) — the backward-compatibility guarantee that makes wiring FleetCoder into
    _fix_loop safe for every existing unrouted build."""
    spec = _sample_spec()
    coder = FakeCoder({"go.mod": [f"```mod\n{GO_MOD}```"],
                       "main.go": [f"```go\n{BAD_GO}```", f"```go\n{GOOD_GO}```"]})
    ok, _ = build(spec, FleetCoder([coder]), tmp_path, max_fix_rounds=4)
    assert ok
    assert (tmp_path / "main.go").read_text() == GOOD_GO
    assert coder.calls.count("main.go") == 2  # generated once, fixed once — same as bare


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
    assert "other files in THIS package" in prompt
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


def test_rule_disabled_is_the_ab_switch_for_prompt_defaults(monkeypatch):
    # Every prompt default here was earned by measuring it against its absence,
    # and each measurement needed an off-arm. Hand-adding a guard per experiment
    # and deleting it after is why the completeness rule's value on a prose-heavy
    # spec went unmeasured for so long — and when it finally was measured, the
    # rule turned out to BREAK that spec. The switch is how that gets caught.
    monkeypatch.delenv("GUILDLM_DISABLE_RULES", raising=False)
    assert not rule_disabled("mutex")

    monkeypatch.setenv("GUILDLM_DISABLE_RULES", "mutex")
    assert rule_disabled("mutex")

    monkeypatch.setenv("GUILDLM_DISABLE_RULES", " mutex , completeness ")
    assert rule_disabled("mutex") and rule_disabled("completeness")

    # An instrument, not config the build depends on: an unknown name is inert.
    monkeypatch.setenv("GUILDLM_DISABLE_RULES", "typo")
    assert not rule_disabled("mutex")


def test_completeness_is_off_by_default_and_opt_in(monkeypatch):
    # It is off because it was MEASURED and did not survive:
    #   ratelimit  0 effect      (two server processes, seven arms — the 42.4
    #                             baseline that justified it never came back)
    #   workapi    +1 test       (TestListSorted, 3/3, real, coverage-invisible)
    #   shortener  loses green   (5/5, across both wordings)
    # A cost that reproduces and a benefit that does not. It stays in the tree,
    # switched off, so the workapi finding is not thrown away with the rule.
    monkeypatch.delenv("GUILDLM_ENABLE_RULES", raising=False)
    off = _test_rule("x_test.go")
    assert "EVERY SCENARIO" not in off
    # Only completeness goes. The rest of the test defaults are not on trial.
    assert "Derive every expected value strictly from the" in off

    monkeypatch.setenv("GUILDLM_ENABLE_RULES", "completeness")
    on = _test_rule("x_test.go")
    assert "EVERY SCENARIO" in on
    # And when it IS on, it must still carry no single spec's furniture: the old
    # wording named ratelimit's own hit()/allow-then-deny scenarios and made the
    # model invent a helper on a spec that shows none.
    for transplant in ("hit()", "allow-then-deny", "two-client", "health-check"):
        assert transplant not in on, f"{transplant!r} is one spec's, not every spec's"
    assert "did not show" in on


@requires_go
def test_restore_dropped_decls_lifts_the_fixture_and_its_methods_back():
    # Rejection alone was measured and found wanting: both draws dropped the same
    # fixture — temp 0.1 and temp 0.6 — so resampling cannot bring it back. The
    # previous version still has it, and the candidate still calls it.
    previous = (
        "package service\n\n"
        "import \"errors\"\n\n"
        "var errBoom = errors.New(\"boom\")\n\n"
        "type failStore struct{}\n\n"
        "func (failStore) ListTasks() error { return errBoom }\n\n"
        "func (failStore) GetTask() error { return errBoom }\n\n"
        "func TestList(t *testing.T) { _ = failStore{} }\n"
    )
    dropped = (
        "package service\n\n"
        "import \"errors\"\n\n"
        "var errBoom = errors.New(\"boom\")\n\n"
        "func TestList(t *testing.T) { _ = failStore{} }\n"
    )
    assert self_dropped_decls(dropped, previous, set()) == {"failStore"}

    fixed = restore_dropped_decls(dropped, previous, {"failStore"})
    # The type comes back WITH its methods — that cluster is what the rewrite lost.
    assert "type failStore struct{}" in fixed
    assert "func (failStore) ListTasks()" in fixed
    assert "func (failStore) GetTask()" in fixed
    # And the file no longer uses what it does not define.
    assert self_dropped_decls(fixed, previous, set()) == set()
    # No second package clause: the payload's own header must not be spliced in.
    assert fixed.count("package service") == 1


def test_sample_clean_falls_back_to_the_first_draw_not_the_hottest():
    # The two repairs compose badly if this is wrong. Stepping the temperature per
    # retry made best-of-N real; it also made `last` the HOTTEST sample. This
    # branch — every draw dirty — is the one the logs hit 320 times, and shipping
    # the hottest reject in place of the near-greedy one would be a regression
    # caused by the fix that made the mechanism work.
    class _Draws:
        def __init__(self):
            self.temps = []

        def generate(self, prompt, temperature=None):
            self.temps.append(temperature)
            # Every draw is dirty: uses `fake`, declares nothing.
            n = len(self.temps)
            return f"```go\npackage p\n\nfunc TestX(t *testing.T) {{ _ = fake{{}}; _ = {n} }}\n```"

    coder = _Draws()
    previous = "package p\n\ntype fake struct{}\n\nfunc TestX(t *testing.T) { _ = fake{} }\n"
    out = _sample_clean(
        coder, "p", True, 2, GoToolchain(), "fix", None, False, None, None, previous
    )
    assert coder.temps == [None, pytest.approx(0.6)], "retry must step the temperature"
    assert "_ = 1" in out and "_ = 2" not in out, "must fall back to the FIRST draw"


def test_self_dropped_decls_catches_the_fixture_the_fix_loop_forgets():
    # The shape, from a real red artifact: the fix loop rewrites the whole test
    # file each round and forgets the package-scope fixtures at the top. 33
    # occurrences over 13 runs on disk; three of those runs burned their entire
    # fix budget oscillating — round 4 drops fakeEnqueuer, round 5 restores it and
    # drops failStore.
    previous = (
        "package service\n\n"
        "var errBoom = errors.New(\"boom\")\n"
        "type failStore struct{}\n\n"
        "func (failStore) ListTasks(ctx context.Context) ([]models.Task, error) "
        "{ return nil, errBoom }\n\n"
        "func TestListStoreError(t *testing.T) { svc := NewTaskService(failStore{}) }\n"
    )
    # The candidate still USES failStore and no longer declares it: `undefined`.
    dropped = "package service\n\nfunc TestListStoreError(t *testing.T) { svc := NewTaskService(failStore{}) }\n"
    assert self_dropped_decls(dropped, previous, set()) == {"failStore"}

    # Dropping something it no longer references is not this bug — a fix is
    # allowed to delete a test and its fixture together.
    gone = "package service\n\nfunc TestOther(t *testing.T) {}\n"
    assert self_dropped_decls(gone, previous, set()) == set()

    # A sibling that provides the name means the candidate is not undefined.
    assert self_dropped_decls(dropped, previous, {"failStore"}) == set()

    # No previous version (generation, not a fix) => nothing to compare against.
    assert self_dropped_decls(dropped, "", set()) == set()


def test_is_clean_rejects_a_fix_that_drops_what_it_still_uses():
    # The rejection is only worth anything because a retry now draws at a
    # different temperature. Before that, redrawing an identical prompt against a
    # deterministic server reproduced the identical defect: 320 dirty redraws, 0
    # rescues.
    previous = "package p\n\ntype fake struct{}\n\nfunc TestX(t *testing.T) { _ = fake{} }\n"
    candidate = "package p\n\nfunc TestX(t *testing.T) { _ = fake{} }\n"
    tc = GoToolchain()
    assert not _is_clean(candidate, True, tc, None, False, None, None, previous)
    # Same candidate, judged as a GENERATION (no previous) — this check is silent.
    assert _is_clean(candidate, True, tc, None, False, None, None, None)


def test_canonical_toolchain_output_strips_cache_and_timing_noise():
    # `(cached)` is the one that bites: go's test cache is machine-global, so the
    # 6th run of a spec sees text the first five did not, and the fix prompt —
    # which embeds this output verbatim — stops being a function of the code.
    cached = "ok  \tguildlm.dev/workapi/internal/api\t(cached)"
    timed = "ok  \tguildlm.dev/workapi/internal/api\t0.710s"
    assert _canonical_toolchain_output(cached) == _canonical_toolchain_output(timed)
    assert _canonical_toolchain_output(cached) == "ok  \tguildlm.dev/workapi/internal/api"

    # Per-test durations move too, and a coverage suffix must survive the strip.
    assert (
        _canonical_toolchain_output("--- FAIL: TestListSorted (0.00s)")
        == "--- FAIL: TestListSorted"
    )
    assert (
        _canonical_toolchain_output("ok  \tpkg\t1.2s\tcoverage: 85.2% of statements")
        == "ok  \tpkg\tcoverage: 85.2% of statements"
    )

    # The diagnostics themselves are untouched — they are the whole payload, and
    # a version number or a line:col must never be mistaken for a duration.
    err = (
        "# guildlm.dev/workapi/internal/service\n"
        "vet: internal/service/service_test.go:165:24: undefined: failStore\n"
        "FAIL\tguildlm.dev/workapi/internal/service [build failed]"
    )
    assert _canonical_toolchain_output(err) == err


def test_fix_prompt_is_identical_whether_go_cached_the_tests():
    # The regression this exists to prevent: same code, same errors, one run
    # reading go's cache and one not => two different prompts => divergence.
    task = FileTask(index=0, spec=FileSpec(path="store_test.go", purpose="tests"))
    fail = "--- FAIL: TestX (0.00s)\n    store_test.go:9: got 2, want 1\nFAIL\tpkg\t"
    a = _fix_prompt(task, "package store", fail + "0.031s\nok  \tother\t0.710s")
    b = _fix_prompt(task, "package store", fail + "0.004s\nok  \tother\t(cached)")
    assert a == b


def test_generate_prompt_test_file_demands_field_named_struct_literals():
    # kvservice/taskapipro class: a positional table-of-cases literal silently
    # puts a value in the wrong field, and `go vet` does not catch it for a
    # same-package struct. The default now steers every test toward field names.
    spec = _sample_spec()
    prompt = _generate_prompt(spec, _impl_task(), {})  # _test.go
    assert "FIELD NAMES" in prompt
    assert "positional literal" in prompt
    # It is test-file guidance, not repeated on the implementation file.
    impl = FileTask(index=1, spec=FileSpec(path="stringkit.go", purpose="impl"))
    assert "FIELD NAMES" not in _generate_prompt(spec, impl, {})


def test_generate_prompt_impl_file_demands_interface_impl_parity():
    # tasks-api/taskapipro/taskflow class: an interface and its implementation
    # must expose the exact same method set. A safe prompt rule instead of a
    # risky AST gate.
    spec = _sample_spec()
    impl = FileTask(index=1, spec=FileSpec(path="store.go", purpose="a Store interface + impl"))
    prompt = _generate_prompt(spec, impl, {})
    assert "INTERFACE/IMPL PARITY" in prompt
    # Not emitted on test files (completeness_rule is implementation-only).
    assert "INTERFACE/IMPL PARITY" not in _generate_prompt(spec, _impl_task(), {})


def test_generate_prompt_list_file_teaches_container_list_idiom():
    # A file whose purpose uses container/list gets the PushFront-takes-a-value
    # idiom; a file that doesn't, doesn't (it's a targeted, not global, rule).
    spec = _sample_spec()
    lru = FileTask(
        index=1,
        spec=FileSpec(path="lru.go", purpose="an LRU cache using container/list and MoveToFront"),
    )
    prompt = _generate_prompt(spec, lru, {})
    assert "CONTAINER/LIST IDIOM" in prompt
    assert "double-wraps" in prompt
    plain = FileTask(index=1, spec=FileSpec(path="store.go", purpose="an in-memory map store"))
    assert "CONTAINER/LIST IDIOM" not in _generate_prompt(spec, plain, {})


def test_generate_prompt_mutex_file_teaches_reentrancy():
    # A file whose purpose guards state with a sync.RWMutex gets the
    # not-reentrant idiom (a write method must not call a read accessor while
    # holding the lock); a file that doesn't mention a mutex, doesn't. The
    # held-out ledger deadlocked on exactly this and the model could not fix it.
    spec = _sample_spec()
    store = FileTask(
        index=1,
        spec=FileSpec(path="memory.go", purpose="an in-memory store guarded by ONE sync.RWMutex"),
    )
    prompt = _generate_prompt(spec, store, {})
    assert "MUTEX REENTRANCY" in prompt
    assert "not reentrant" in prompt.lower()
    # A file with no mutex in its purpose does not carry the rule.
    plain = FileTask(index=1, spec=FileSpec(path="handlers.go", purpose="http handlers over a store"))
    assert "MUTEX REENTRANCY" not in _generate_prompt(spec, plain, {})
    # Neither does a test file, even one that mentions the mutex.
    tst = FileTask(
        index=1,
        spec=FileSpec(path="memory_test.go", purpose="tests for the sync.RWMutex store"),
    )
    assert "MUTEX REENTRANCY" not in _generate_prompt(spec, tst, {})


def test_generate_prompt_routing_file_demands_method_value_registration():
    # tasks-api/ratelimit class: register a handler by passing the method value,
    # never by calling it. Fires only when the purpose is about routing.
    spec = _sample_spec()
    router = FileTask(
        index=1,
        spec=FileSpec(path="router.go", purpose="build an http.ServeMux and register routes"),
    )
    prompt = _generate_prompt(spec, router, {})
    assert "method VALUE" in prompt
    assert "never by CALLING" in prompt
    # A non-routing implementation file does not carry the routing rule.
    plain = FileTask(index=1, spec=FileSpec(path="store.go", purpose="an in-memory store"))
    assert "method VALUE" not in _generate_prompt(spec, plain, {})


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
        self.temps = []

    def generate(self, prompt, temperature=None):
        self.seen.append(prompt)
        self.temps.append(temperature)
        return self.tag


def test_role_routing_forwards_the_resample_temperature():
    # RoleRoutingCoder delegates, so it must carry the temperature through —
    # otherwise best-of-N silently reverts to drawing the same sample twice for
    # exactly the roles that route, and nowhere else.
    dev, test = _TagCoder("DEV"), _TagCoder("TEST")
    coder = RoleRoutingCoder({"dev": dev, "test": test})
    coder.generate("TARGET_FILE: store.go\n...", 0.6)
    assert dev.temps == [0.6]


def test_resample_temperature_steps_only_after_the_first_draw():
    # Attempt 0 must stay on the coder's default (None): the common path is a
    # clean first draw, and it must not change behaviour. Retries step, because
    # an identical (prompt, temperature) returns an identical file — which is why
    # `kept candidate 2 of 2` appears zero times in 3225 logged draws.
    assert _resample_temperature(0) is None
    assert _resample_temperature(1) == pytest.approx(0.6)  # 0.1 base + 0.5 step
    assert _resample_temperature(2) == pytest.approx(1.1)


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


@requires_go
def test_maintain_applies_change_and_stays_green(tmp_path):
    """maintain() reads an existing green project, applies a change request via a
    plan->edit->verify loop, and leaves it green with the change applied."""
    from src.builder import maintain

    (tmp_path / "go.mod").write_text("module example.com/calc\n\ngo 1.23\n")
    (tmp_path / "calc.go").write_text(
        "package sandbox\n\nfunc Add(a, b int) int {\n\treturn a + b\n}\n"
    )
    (tmp_path / "calc_test.go").write_text(
        "package sandbox\n\nimport \"testing\"\n\n"
        "func TestAdd(t *testing.T) { if Add(1, 2) != 3 { t.Fatal(\"x\") } }\n"
    )
    coder = FakeCoder({
        "?": ["calc.go"],  # plan prompt (no TARGET_FILE) -> edit calc.go
        "calc.go": [
            "```go\npackage sandbox\n\nfunc Add(a, b int) int {\n\treturn a + b\n}\n\n"
            "func Sub(a, b int) int {\n\treturn a - b\n}\n```"
        ],
    })
    ok, _ = maintain(str(tmp_path), "add a Sub function", coder, toolchain=GoToolchain())
    assert ok
    assert "func Sub" in (tmp_path / "calc.go").read_text()
    green, _ = GoToolchain().check(tmp_path)
    assert green


@requires_go
def test_maintain_rolls_back_when_not_green(tmp_path):
    """A non-regressing maintain reverts to the original sources when the edit
    can't converge to green — maintenance never leaves the project worse."""
    from src.builder import maintain

    orig = "package sandbox\n\nfunc Add(a, b int) int {\n\treturn a + b\n}\n"
    (tmp_path / "go.mod").write_text("module example.com/calc\n\ngo 1.23\n")
    (tmp_path / "calc.go").write_text(orig)
    coder = FakeCoder({
        "?": ["calc.go"],
        "calc.go": ["```go\npackage sandbox\n\nfunc Add(a, b int) int { return a + b // oops\n```"],
    })
    ok, _ = maintain(str(tmp_path), "break it", coder, toolchain=GoToolchain(), max_fix_rounds=1)
    assert not ok
    assert (tmp_path / "calc.go").read_text() == orig  # rolled back


@requires_go
def test_write_tests_generates_passing_tests(tmp_path):
    """write_tests() asks go-test for a _test.go for an existing project and loops
    it to green: the generated test compiles, asserts, and passes."""
    from src.builder import write_tests

    (tmp_path / "go.mod").write_text("module example.com/calc\n\ngo 1.23\n")
    (tmp_path / "calc.go").write_text(
        "package sandbox\n\nfunc Add(a, b int) int {\n\treturn a + b\n}\n"
    )
    coder = FakeCoder({
        "guild_test.go": [
            "```go\npackage sandbox\n\nimport \"testing\"\n\n"
            "func TestAdd(t *testing.T) {\n\tif Add(1, 2) != 3 {\n\t\tt.Fatal(\"add\")\n\t}\n}\n```"
        ],
    })
    ok, content = write_tests(str(tmp_path), coder, toolchain=GoToolchain())
    assert ok
    assert "func TestAdd" in content
    assert (tmp_path / "guild_test.go").exists()


def test_check_appends_vet_output_when_build_fails(tmp_path):
    # go build never compiles _test.go files: with the impl broken in one
    # package, a test-file compile error in ANOTHER package must still be
    # visible in check() output (vet supplies it), or the fix loop pays one
    # round per error layer.
    (tmp_path / "go.mod").write_text("module example.com/m\n\ngo 1.22\n")
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "a.go").write_text(
        "package a\n\nfunc F() int { return undefinedSymbol }\n"
    )
    (b / "b.go").write_text("package b\n\nfunc G() int { return 1 }\n")
    (b / "b_test.go").write_text(
        "package b\n\nimport \"testing\"\n\n"
        "func TestG(t *testing.T) {\n\t_ = alsoUndefined\n}\n"
    )
    ok, output = GoToolchain().check(tmp_path)
    assert not ok
    assert "undefinedSymbol" in output  # the build error
    assert "alsoUndefined" in output  # the test-file error only vet surfaces


def test_write_file_returns_what_landed_on_disk(tmp_path):
    # written[] must hold the gofmt'd content, or compiler line numbers drift
    # from the stored source and line-indexed gates miss their target lines
    from src.builder import _write_file

    raw = "package a\n\n\n\nfunc   f(  ) {\n\treturn\n}\n"
    stored = _write_file(tmp_path, "a.go", raw)
    on_disk = (tmp_path / "a.go").read_text()
    assert stored == on_disk
    assert stored != raw  # gofmt actually reflowed it


def test_error_signature_strips_run_noise():
    from src.builder import _error_signature

    a = (
        "panic({0x1049b69c0?, 0x14000018108?})\n"
        "created by testing.(*T).Run in goroutine 6\n"
        "\tservice_test.go:48 +0x324\n"
        "FAIL\tguildlm.dev/workapi/internal/service\t1.093s\n"
    )
    b = (
        "panic({0x10027e9c0?, 0x14000124048?})\n"
        "created by testing.(*T).Run in goroutine 34\n"
        "\tservice_test.go:48 +0x1c8\n"
        "FAIL\tguildlm.dev/workapi/internal/service\t0.745s\n"
    )
    assert _error_signature(a) == _error_signature(b)
    c = b.replace("service_test.go:48", "service_test.go:52")
    assert _error_signature(b) != _error_signature(c)


def test_trace_writes_and_harvests(tmp_path, monkeypatch):
    import json as _json
    from src.builder import _trace

    trace = tmp_path / "run.jsonl"
    monkeypatch.setenv("GUILDLM_BUILDER_TRACE", str(trace))
    _trace({"stage": "generate", "path": "a.go", "prompt": "P1", "response": "old"})
    _trace({"stage": "fix", "path": "a.go", "prompt": "P2", "response": "mid"})
    _trace({"event": "green", "spec": "s", "files": {"a.go": "final", "go.mod": "m"}})

    sys_path_hack = None  # harvest is a script, import by path
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("harvest_traces", "harvest_traces.py")
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = mod.harvest(trace)
    # one row per .go file, LAST prompt paired with FINAL green content
    assert len(rows) == 1
    assert rows[0]["instruction"] == "P2"
    assert "final" in rows[0]["response"]


def test_trace_disabled_is_noop(tmp_path, monkeypatch):
    from src.builder import _trace

    monkeypatch.delenv("GUILDLM_BUILDER_TRACE", raising=False)
    _trace({"stage": "generate"})  # must not raise or create anything
    assert list(tmp_path.iterdir()) == []


def test_nomethod_widening_targets_type_declaration():
    from src.builder import _widen_missing_symbol_targets

    written = {
        "handlers.go": "package main\n\nfunc h() { _ = store.Update }\n",
        "store.go": "package main\n\ntype Store interface {\n\tCreate() error\n}\n",
        "store_test.go": "package main\n",
    }
    err = (
        "./handlers.go:80:20: a.store.Update undefined "
        "(type Store has no field or method Update)"
    )
    out = _widen_missing_symbol_targets(["handlers.go"], written, err)
    assert "store.go" in out  # the declaration site joins the fix targets
    assert "store_test.go" not in out


def test_required_decls_includes_func_main():
    from src.builder import _required_decls

    assert "main" in _required_decls(
        "package main. func main() wiring the server with graceful shutdown."
    )
    assert "main" not in _required_decls("package api. HTTP handlers.")


def test_test_rule_teaches_seeding_not_just_isolation():
    """The old ISOLATE-STATE default taught only half the rule — construct a fresh
    instance per case — and a fresh instance is EMPTY. Six specs in a row wrote a
    `duplicate -> 409` case against a store nobody had written to, got 201, and
    failed no matter how correct the handler was. The default must carry the other
    half: seed your own precondition."""
    spec = Spec(
        name="x",
        description="d",
        files=(FileSpec(path="router_test.go", purpose="package main. Tests."),),
    )
    prompt = _generate_prompt(spec, plan(spec)[0], {}, None)
    assert "ISOLATE STATE, THEN SEED IT" in prompt
    assert "CREATE that precondition ITSELF" in prompt
    assert "SEPARATE FOCUSED TEST FUNCTIONS" in prompt
    assert "ASSERT ON WHAT YOU JUST FETCHED" in prompt


def test_seeding_rule_is_absent_from_non_test_files():
    spec = Spec(
        name="x",
        description="d",
        files=(FileSpec(path="store.go", purpose="package main. A store."),),
    )
    prompt = _generate_prompt(spec, plan(spec)[0], {}, None)
    assert "ISOLATE STATE, THEN SEED IT" not in prompt


def test_empty_go_files_finds_a_file_a_sibling_emptied():
    """Every multi-package artifact in the suite shipped a bare `package store` —
    the model implemented MemStore in store.go, so memory.go had nothing left to
    declare. Go compiles it happily; only an explicit check notices."""
    from src.builder import empty_go_files

    written = {
        "store.go": "package store\n\ntype Store interface{ Get() error }\n"
        "type MemStore struct{}\n\nfunc (m *MemStore) Get() error { return nil }\n",
        "memory.go": "package store\n",
        "store_test.go": "package store\n",   # a test file is not our business
    }
    assert empty_go_files(written) == ["memory.go"]


def test_empty_go_files_accepts_a_file_that_declares_something():
    from src.builder import empty_go_files

    written = {"memory.go": "package store\n\ntype MemStore struct{}\n"}
    assert empty_go_files(written) == []


def test_scope_rule_tells_a_file_to_stay_in_its_lane():
    spec = Spec(
        name="x",
        description="d",
        files=(
            FileSpec(path="store.go", purpose="package store. The Store interface."),
            FileSpec(path="memory.go", purpose="package store. The MemStore impl."),
        ),
    )
    prompt = _generate_prompt(spec, plan(spec)[0], {}, None)
    assert "STAY IN YOUR LANE" in prompt


def test_scope_rule_is_absent_when_the_file_stands_alone():
    spec = Spec(
        name="x",
        description="d",
        files=(FileSpec(path="main.go", purpose="package main. Everything."),),
    )
    prompt = _generate_prompt(spec, plan(spec)[0], {}, None)
    assert "STAY IN YOUR LANE" not in prompt


def test_isolate_state_names_the_thing_that_holds_the_state():
    """ratelimit failed because its spec said "each subtest builds its OWN mux" —
    and the mux is stateless. The registry underneath, built ONCE outside, kept the
    token buckets, so the first subtest spent clientA's only token and the second
    got 429 where it wanted 200. The default had the same flaw: it named the
    wrapper (server/handler) rather than the thing that remembers."""
    spec = Spec(
        name="x",
        description="d",
        files=(FileSpec(path="router_test.go", purpose="package main. Tests."),),
    )
    prompt = _generate_prompt(spec, plan(spec)[0], {}, None)
    assert "HOLDS THE STATE" in prompt
    assert "isolates NOTHING" in prompt


def test_why_dirty_names_the_rule_that_rejected_a_candidate():
    # `no clean candidate` never said WHICH check fired. A rejection landed in the
    # same round as an `undefined: failStore`, the two looked consistent, and I was
    # one inference from crediting the rule I had just written. A log that only
    # reports my own check's rejections is how a correlation gets read as a cause.
    tc = GoToolchain()
    assert why_dirty("package p\n\nfunc (", True, tc) == "does not parse"
    assert "foreign import" in why_dirty(
        'package p\n\nimport "github.com/gorilla/mux"\n\nvar _ = mux.NewRouter\n',
        True, tc, module="example.com/demo",
    )
    assert "redeclares a sibling's Store" in why_dirty(
        "package p\n\ntype Store struct{}\n", True, tc, {"Store"}
    )
    previous = "package p\n\ntype fake struct{}\n\nfunc TestX(t *testing.T) { _ = fake{} }\n"
    assert "drops fake" in why_dirty(
        "package p\n\nfunc TestX(t *testing.T) { _ = fake{} }\n",
        True, tc, None, False, None, None, previous,
    )
    assert why_dirty("package p\n\nfunc TestX(t *testing.T) { t.Fatal(1) }\n", True, tc) == ""


@requires_go
def test_restore_repairs_the_real_recorded_failure(tmp_path):
    # THE MEASUREMENT, distilled from the artifact it was taken on. workapi's
    # without-3 run burned all five fix rounds and stayed red on exactly this:
    #   vet: internal/service/service_test.go:165:24: undefined: failStore
    # The model's rewrite dropped the fixture and kept the two calls to it. Five
    # model fix-rounds could not put it back; one deterministic splice does. On
    # the real tree that repair takes go vet from rc=1 to rc=0 and the whole
    # artifact to a green build+vet+test.
    #
    # The shape is the REAL one: errBoom survives, failStore does not. An earlier
    # draft of this test dropped both, which movedecls cannot repair (it moves
    # types and funcs, never vars) — a case the real failure never produced. The
    # test exists because the artifacts are not in git and _ab_run.sh rm -rf's
    # them between runs.
    (tmp_path / "go.mod").write_text("module example.com/demo\n\ngo 1.23\n")
    previous = (
        "package demo\n\n"
        "import (\n\t\"errors\"\n\t\"testing\"\n)\n\n"
        "var errBoom = errors.New(\"boom\")\n\n"
        "type failStore struct{}\n\n"
        "func (failStore) List() error { return errBoom }\n\n"
        "func TestListError(t *testing.T) {\n\tvar s failStore\n\t_ = s.List()\n}\n"
    )
    (tmp_path / "demo_test.go").write_text(previous)
    assert GoToolchain().vet(tmp_path)[0], "the previous version must compile"

    # The rewrite the fix loop actually produces: fixture gone, its var kept, the
    # calls to it kept.
    dropped = (
        "package demo\n\n"
        "import (\n\t\"errors\"\n\t\"testing\"\n)\n\n"
        "var errBoom = errors.New(\"boom\")\n\n"
        "func TestListError(t *testing.T) {\n\tvar s failStore\n\t_ = s.List()\n}\n"
    )
    (tmp_path / "demo_test.go").write_text(dropped)
    ok, out = GoToolchain().vet(tmp_path)
    assert not ok and "undefined: failStore" in out, out

    fixed = restore_dropped_decls(dropped, previous, self_dropped_decls(dropped, previous, set()))
    (tmp_path / "demo_test.go").write_text(fixed)
    ok, out = GoToolchain().vet(tmp_path)
    assert ok, f"the repair must make the real shape compile: {out}"
