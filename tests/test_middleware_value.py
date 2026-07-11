"""Pass the middleware, don't call it.

    type Middleware func(http.Handler) http.Handler
    func Logging(next http.Handler) http.Handler { ... }   // already a Middleware

    Chain(mux, Logging(logger), Recover(logger))   // the model calls them
    Chain(mux, Logging, Recover)                   // it should hand them over

The mirror of the existing middleware-arity gate: that one repairs a DEFINITION
written in the wrong shape; here the definition is right and the call site is
wrong.
"""

import shutil

import pytest

from src.builder import _fix_middleware_called_not_passed, _run_deterministic_gates

pytestmark = pytest.mark.skipif(
    shutil.which("go") is None, reason="needs the Go toolchain"
)

MW = """package api

import "net/http"

type Middleware func(http.Handler) http.Handler

func Chain(h http.Handler, mws ...Middleware) http.Handler { return h }

func Logging(next http.Handler) http.Handler { return next }
"""

ROUTER = """package api

import (
	"log/slog"
	"net/http"
)

func NewRouter(logger *slog.Logger) http.Handler {
	mux := http.NewServeMux()
	return Chain(mux, Logging(logger))
}
"""

WRITTEN = {"api/middleware.go": MW, "api/router.go": ROUTER}


def _err_at(src: str, needle: str, want: str = "Middleware") -> str:
    line = next(i for i, l in enumerate(src.splitlines(), 1) if needle in l)
    col = src.splitlines()[line - 1].index(needle) + 1
    return (
        f"./api/router.go:{line}:{col}: cannot use {needle} "
        f"(value of interface type http.Handler) as {want} value in argument to Chain"
    )


ERR = _err_at(ROUTER, "Logging(logger)")


def test_passes_the_middleware_by_value():
    body = _fix_middleware_called_not_passed(WRITTEN, ERR)["api/router.go"]
    assert "Chain(mux, Logging)" in body
    assert "Logging(logger)" not in body
    assert "func Logging(next http.Handler) http.Handler" not in body  # def untouched


def test_noop_when_the_signature_does_not_match_the_wanted_type():
    # Logging takes a logger too, so its value is NOT a Middleware — this is the
    # DEFINITION-shape bug, which belongs to the older middleware-arity gate.
    mw = MW.replace(
        "func Logging(next http.Handler) http.Handler",
        "func Logging(next http.Handler, log *slog.Logger) http.Handler",
    )
    assert _fix_middleware_called_not_passed({**WRITTEN, "api/middleware.go": mw}, ERR) == {}


def test_noop_when_the_wanted_type_is_not_a_func_type():
    # `as *API value` — an *API is not something a function value can become.
    err = _err_at(ROUTER, "Logging(logger)", want="*API")
    assert _fix_middleware_called_not_passed(WRITTEN, err) == {}


def test_noop_when_the_function_is_unknown():
    written = {"api/router.go": ROUTER}  # no middleware.go: Logging undeclared
    assert _fix_middleware_called_not_passed(written, ERR) == {}


def test_noop_without_the_error():
    assert _fix_middleware_called_not_passed(WRITTEN, "") == {}


def test_composes_in_the_deterministic_gate_chain():
    out = _run_deterministic_gates(WRITTEN, ERR, None)
    assert "Chain(mux, Logging)" in out["api/router.go"]
