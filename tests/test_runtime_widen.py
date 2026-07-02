"""Tests for root-cause fix-target widening + the state-isolation fix hint."""

from src.builder import _widen_runtime_targets

RUNTIME_FAIL = (
    "--- FAIL: TestLoad (0.00s)\n"
    "    config_test.go:11: Addr = , want :8080\n"
    "FAIL\tguildlm.dev/app/internal/config\t0.4s\n"
)
COMPILE_FAIL = "internal/config/config_test.go:11:2: undefined: Load"

WRITTEN = {
    "internal/config/config.go": "package config",
    "internal/config/config_test.go": "package config",
    "internal/store/store.go": "package store",
}


def test_first_runtime_round_stays_on_the_test_file():
    rounds = {}
    t = _widen_runtime_targets(
        ["internal/config/config_test.go"], WRITTEN, rounds, RUNTIME_FAIL
    )
    assert t == ["internal/config/config_test.go"]
    assert rounds == {"internal/config": 1}


def test_persistent_runtime_failure_widens_to_package_impl():
    rounds = {"internal/config": 1}
    t = _widen_runtime_targets(
        ["internal/config/config_test.go"], WRITTEN, rounds, RUNTIME_FAIL
    )
    assert t == [
        "internal/config/config_test.go",
        "internal/config/config.go",
    ]
    # other packages' files are never dragged in
    assert "internal/store/store.go" not in t


def test_compile_errors_never_widen():
    rounds = {"internal/config": 5}
    t = _widen_runtime_targets(
        ["internal/config/config_test.go"], WRITTEN, rounds, COMPILE_FAIL
    )
    assert t == ["internal/config/config_test.go"]
    assert rounds == {"internal/config": 5}  # untouched


def test_fix_prompt_gets_isolation_hint_on_runtime_test_failure():
    from src.builder import _fix_prompt, FileTask, FileSpec

    task = FileTask(
        index=0,
        spec=FileSpec(path="internal/store/memory_test.go", purpose="tests"),
    )
    p = _fix_prompt(task, "package store", RUNTIME_FAIL)
    assert "FRESH store/server INSIDE each t.Run" in p
    # compile errors do not get the runtime diagnosis
    p2 = _fix_prompt(task, "package store", COMPILE_FAIL)
    assert "FRESH store/server INSIDE" not in p2
