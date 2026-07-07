from src.builder import _fix_errors_wrap, _run_deterministic_gates


def test_rewrites_wrap_to_errorf_and_ensures_fmt():
    written = {
        "parse.go": (
            'package main\n\nimport (\n\t"errors"\n)\n\n'
            "var ErrBadLine = errors.New(\"bad line\")\n\n"
            "func parse() error {\n"
            '\treturn errors.Wrap(ErrBadLine, "expected 5 fields")\n'
            "}\n"
        )
    }
    err = "./parse.go:10:9: undefined: errors.Wrap"
    out = _fix_errors_wrap(written, err)
    body = out["parse.go"]
    assert 'fmt.Errorf("expected 5 fields: %w", ErrBadLine)' in body
    assert "errors.Wrap(" not in body
    assert '"fmt"' in body  # import ensured
    assert '"errors"' in body  # errors kept (still used by errors.New)


def test_rewrites_wrapf_reorders_wrapped_error_last():
    written = {
        "a.go": (
            'package a\n\nimport "errors"\n\n'
            "func f(err error, name string) error {\n"
            '\treturn errors.Wrapf(err, "loading %s", name)\n'
            "}\n"
        )
    }
    err = "./a.go:6:9: undefined: errors.Wrapf"
    out = _fix_errors_wrap(written, err)
    body = out["a.go"]
    # fmt string gets ": %w"; the format arg stays, the error moves to the end.
    assert 'fmt.Errorf("loading %s: %w", name, err)' in body
    assert '"fmt"' in body


def test_multiple_wraps_same_file_all_fixed():
    written = {
        "p.go": (
            'package p\n\nimport "errors"\n\n'
            "func a(e error) error { return errors.Wrap(e, \"a\") }\n"
            "func b(e error) error { return errors.Wrap(e, \"b\") }\n"
        )
    }
    err = "./p.go:5:31: undefined: errors.Wrap\n./p.go:6:31: undefined: errors.Wrap"
    out = _fix_errors_wrap(written, err)
    body = out["p.go"]
    assert 'fmt.Errorf("a: %w", e)' in body
    assert 'fmt.Errorf("b: %w", e)' in body
    assert "errors.Wrap(" not in body


def test_nested_parens_in_error_arg_preserved():
    written = {
        "a.go": (
            'package a\n\nimport "errors"\n\n'
            'func f() error { return errors.Wrap(do(x, y), "ctx") }\n'
        )
    }
    err = "./a.go:5:32: undefined: errors.Wrap"
    out = _fix_errors_wrap(written, err)
    assert 'fmt.Errorf("ctx: %w", do(x, y))' in out["a.go"]


def test_non_literal_message_left_alone():
    # a variable message can't be safely folded into the format string -> skip
    written = {"a.go": 'package a\nimport "errors"\nfunc f(e error, m string) error { return errors.Wrap(e, m) }\n'}
    err = "./a.go:3:40: undefined: errors.Wrap"
    assert _fix_errors_wrap(written, err) == {}


def test_no_error_no_change():
    written = {"a.go": 'package a\nfunc f(){}\n'}
    assert _fix_errors_wrap(written, "") == {}


def test_composes_in_deterministic_gate_chain():
    written = {
        "parse.go": (
            'package main\n\nimport "errors"\n\n'
            "func parse() error {\n"
            '\treturn errors.Wrap(errors.New("x"), "ctx")\n'
            "}\n"
        )
    }
    err = "./parse.go:6:9: undefined: errors.Wrap"
    out = _run_deterministic_gates(written, err, None)
    assert 'fmt.Errorf("ctx: %w", errors.New("x"))' in out["parse.go"]
