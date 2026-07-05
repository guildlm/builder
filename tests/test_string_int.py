from src.builder import _fix_string_int_conversion


def test_rewrites_string_int_to_strconv_itoa_and_imports():
    written = {
        "internal/worker/worker_test.go": (
            "package worker\n\nimport (\n\t\"testing\"\n)\n\n"
            "func TestX(target *testing.T) {\n"
            '\tid := "task" + string(i)\n'
            "}\n"
        )
    }
    err = (
        "internal/worker/worker_test.go:8:22: conversion from int to string "
        "yields a string of one rune, not a string of digits"
    )
    out = _fix_string_int_conversion(written, err)
    body = out["internal/worker/worker_test.go"]
    assert "strconv.Itoa(i)" in body
    assert "string(i)" not in body
    assert '"strconv"' in body  # import ensured


def test_handles_nested_parens_in_arg():
    written = {
        "a.go": 'package a\nfunc f(){ _ = string(len(xs) - 1) }\n',
    }
    err = "a.go:2:20: conversion from int to string yields a string of one rune"
    out = _fix_string_int_conversion(written, err)
    assert "strconv.Itoa(len(xs) - 1)" in out["a.go"]


def test_leaves_unflagged_string_conversions_alone():
    # no error reported -> no change (a legitimate string([]byte) stays)
    written = {"a.go": "package a\nfunc f(b []byte){ _ = string(b) }\n"}
    assert _fix_string_int_conversion(written, "") == {}
