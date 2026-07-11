"""The adapter-insertion gate.

`NewRouter(NewMemStore())` — the model wired the router straight to the store and
skipped the layer in between, even though the spec spells the composition out as
NewRouter(NewAPI(NewStore())). When the project declares exactly one function
that turns what you have into what is wanted, the composition it meant is not in
doubt.
"""

import shutil

import pytest

from src.builder import _fix_argument_type_adapter, _run_deterministic_gates

pytestmark = pytest.mark.skipif(
    shutil.which("go") is None, reason="needs the Go toolchain"
)

IMPL = """package main

type Store interface{ Get(id int) error }

type API struct{ store Store }

func NewAPI(store Store) *API { return &API{store: store} }

func NewRouter(api *API) *ServeMux { return nil }

func NewStore() Store { return nil }
"""

TEST = """package main

import "testing"

func newRouter() *ServeMux { return NewRouter(NewStore()) }

func TestX(t *testing.T) { _ = newRouter() }
"""

WRITTEN = {"api.go": IMPL, "handlers_test.go": TEST}


def _err_at(src: str, needle: str, want: str = "*API") -> str:
    """The compiler names the argument by line:column, so derive it from the
    source rather than hand-counting it into a brittle literal."""
    line = next(i for i, l in enumerate(src.splitlines(), 1) if needle in l)
    col = src.splitlines()[line - 1].index(needle) + 1
    return (
        f"./handlers_test.go:{line}:{col}: cannot use {needle} "
        f"(value of interface type Store) as {want} value in argument to NewRouter"
    )


ERR = _err_at(TEST, "NewStore()")


def test_wraps_the_argument_in_the_only_adapter_that_fits():
    body = _fix_argument_type_adapter(WRITTEN, ERR)["handlers_test.go"]
    assert "NewRouter(NewAPI(NewStore()))" in body
    assert "api.go" not in _fix_argument_type_adapter(WRITTEN, ERR)


def test_noop_when_no_adapter_exists():
    impl = IMPL.replace("func NewAPI(store Store) *API { return &API{store: store} }", "")
    assert _fix_argument_type_adapter({**WRITTEN, "api.go": impl}, ERR) == {}


def test_noop_when_two_adapters_could_be_meant():
    # Two Store -> *API functions: wrapping in either one would be a guess.
    impl = IMPL + "\nfunc NewAPIv2(store Store) *API { return &API{store: store} }\n"
    assert _fix_argument_type_adapter({**WRITTEN, "api.go": impl}, ERR) == {}


def test_noop_when_the_adapter_does_not_return_what_is_wanted():
    # NewAPI returns *API, but the call wants a *Mux — not our adapter.
    err = ERR.replace("as *API value", "as *Mux value")
    assert _fix_argument_type_adapter(WRITTEN, err) == {}


def test_noop_when_already_wrapped():
    # Idempotent: a second round must not nest NewAPI(NewAPI(...)). The error is
    # aimed squarely at the ALREADY-WRAPPED argument, so the gate has to refuse on
    # the merits and not merely miss the position.
    test = TEST.replace("NewRouter(NewStore())", "NewRouter(NewAPI(NewStore()))")
    err = _err_at(test, "NewAPI(NewStore())")
    assert _fix_argument_type_adapter({**WRITTEN, "handlers_test.go": test}, err) == {}


def test_noop_without_the_error():
    assert _fix_argument_type_adapter(WRITTEN, "") == {}


def test_composes_in_the_deterministic_gate_chain():
    out = _run_deterministic_gates(WRITTEN, ERR, None)
    assert "NewRouter(NewAPI(NewStore()))" in out["handlers_test.go"]
