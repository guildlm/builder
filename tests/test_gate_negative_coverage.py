"""Fire/bail coverage for phase-1 gates the coverage audit found untested.

An AST audit of gate negative-test coverage (2026-07-20) found six deterministic
gates with no does-not-fire test — the "a gate that rejects correct code is worse
than no gate" risk, unguarded. This file closes the two pure-Python ones that were
worst off: _fix_atomic_inc (no unit test at all) and _fix_mux_return_type (only a
line-count assertion, no behavioural or bail test). Each gets a POSITIVE (it fires
and repairs) and a NEGATIVE that exercises a real safety guard — not merely an
empty error, which would only prove the regex does not match nothing.
"""

from src.builder import _fix_atomic_inc, _fix_mux_return_type


def test_atomic_inc_rewrites_inc_to_add_one():
    code = "package p\n\nfunc f() {\n\tc.Inc()\n}\n"
    err = ('./c.go:4:2: c.Inc undefined '
           '(type "sync/atomic".Int64 has no field or method Inc)')
    out = _fix_atomic_inc({"c.go": code}, err)
    assert out["c.go"].splitlines()[3].strip() == "c.Add(1)"
    assert len(out["c.go"].splitlines()) == len(code.splitlines())  # phase one


def test_atomic_inc_bails_when_the_named_line_lacks_the_call():
    # The compiler names line 4, but c.Inc() is on line 5 — source and diagnostic
    # disagree, so the safe move is to leave it: a blind edit of line 4 would
    # corrupt an unrelated statement.
    code = "package p\n\nfunc f() {\n\t_ = 1\n\tc.Inc()\n}\n"
    err = ('./c.go:4:2: c.Inc undefined '
           '(type "sync/atomic".Int64 has no field or method Inc)')
    assert _fix_atomic_inc({"c.go": code}, err) == {}


def test_mux_return_type_widens_servemux_to_handler():
    code = "package p\n\nfunc newRouter() *http.ServeMux {\n\treturn Chain(mux)\n}\n"
    err = ('./r.go:4:9: cannot use Chain(mux) (value of interface type '
           'http.Handler) as *http.ServeMux value in return statement: need type '
           'assertion')
    out = _fix_mux_return_type({"r.go": code}, err)
    assert "func newRouter() http.Handler {" in out["r.go"]
    assert len(out["r.go"].splitlines()) == len(code.splitlines())  # phase one


def test_mux_return_type_leaves_an_already_correct_signature_alone():
    # The return type is already http.Handler; there is nothing to widen, so even
    # with the diagnostic present the gate must not touch the file.
    code = "package p\n\nfunc newRouter() http.Handler {\n\treturn Chain(mux)\n}\n"
    err = ('./r.go:4:9: cannot use Chain(mux) (value of interface type '
           'http.Handler) as *http.ServeMux value in return statement: need type '
           'assertion')
    assert _fix_mux_return_type({"r.go": code}, err) == {}
