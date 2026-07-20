"""Fire/bail coverage for the two STRUCTURAL gates the audit left uncovered.

_fix_drained_request and _fix_dead_error_assertion are the only gates driven not by
a compiler diagnostic but by an unconditional property of the source, and they
delegate the decision to an external Go tool (tools/freshreq.go, tools/deadassert.go)
via `go run`. The negative-coverage audit (logs/FINDING-gate-negative-coverage.txt)
found neither had any unit test — closed here with a POSITIVE (it fires and repairs)
and a NEGATIVE that exercises the tool's real safety guard, so a loosened guard that
started over-firing on correct code would fail here.

Skipped without the Go toolchain, like the other tool-backed gate tests.
"""

import shutil

import pytest

from src.builder import _fix_dead_error_assertion, _fix_drained_request

pytestmark = pytest.mark.skipif(
    shutil.which("go") is None, reason="needs the Go toolchain"
)


# ------------------------------------------------------- _fix_drained_request

_SERVE_TWICE = """package api

import (
\t"bytes"
\t"net/http/httptest"
\t"testing"
)

func TestDup(t *testing.T) {
\tbody := `{"id":"1"}`
\treq := httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(body))
\tw := httptest.NewRecorder()
\th.ServeHTTP(w, req)
\tw = httptest.NewRecorder()
\th.ServeHTTP(w, req)
}
"""


def test_drained_request_rebuilds_a_request_served_twice():
    out = _fix_drained_request({"api_test.go": _SERVE_TWICE}, "")
    body = out["api_test.go"]
    # the second ServeHTTP now gets a fresh request, so NewRequest appears twice
    assert body.count("httptest.NewRequest") == 2


def test_drained_request_leaves_an_already_rebuilt_request_alone():
    # The author already reassigns req between the two ServeHTTP calls, so the
    # second body is fresh — nothing to repair. A gate that rewrote this would be
    # touching correct code.
    already_rebuilt = _SERVE_TWICE.replace(
        '\tw = httptest.NewRecorder()\n\th.ServeHTTP(w, req)',
        '\treq = httptest.NewRequest("POST", "/tasks", bytes.NewBufferString(body))\n'
        '\tw = httptest.NewRecorder()\n\th.ServeHTTP(w, req)',
    )
    assert _fix_drained_request({"api_test.go": already_rebuilt}, "") == {}


# -------------------------------------------------- _fix_dead_error_assertion

_DEAD_GUARD = """package svc

import (
\t"errors"
\t"testing"
)

func TestListErr(t *testing.T) {
\t_, err := svc.List(ctx)
\tif err != nil {
\t\tt.Fatalf("List: %v", err)
\t}
\tif !errors.Is(err, errBoom) {
\t\tt.Fatalf("want errBoom, got %v", err)
\t}
}
"""


def test_dead_error_assertion_removes_the_dead_happy_path_guard():
    out = _fix_dead_error_assertion({"svc_test.go": _DEAD_GUARD}, "")
    body = out["svc_test.go"]
    # the `if err != nil { t.Fatalf }` guard that made errors.Is unreachable is gone
    assert "if err != nil {" not in body
    assert "errors.Is(err, errBoom)" in body  # the assertion it was hiding survives


def test_dead_error_assertion_keeps_a_guard_when_errors_is_checks_a_different_err():
    # The guard is on `err`; the errors.Is check is on `err2`. They are unrelated,
    # so the happy-path guard is legitimate and must be left in place.
    legit = """package svc

import (
\t"errors"
\t"testing"
)

func TestListErr(t *testing.T) {
\t_, err := svc.List(ctx)
\tif err != nil {
\t\tt.Fatalf("List: %v", err)
\t}
\t_, err2 := other()
\tif !errors.Is(err2, errBoom) {
\t\tt.Fatalf("want errBoom")
\t}
}
"""
    assert _fix_dead_error_assertion({"svc_test.go": legit}, "") == {}
