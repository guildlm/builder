from src.builder import _fix_uncalled_method_value, _run_deterministic_gates


def test_inserts_parens_on_recorder_header():
    written = {
        "x_test.go": (
            "package main\n\nfunc f(rec R) {\n"
            "\tif rec.Header.Get(\"Retry-After\") != \"1\" {\n\t}\n}\n"
        )
    }
    err = (
        "./x_test.go:4:14: rec.Header.Get undefined "
        "(type func() http.Header has no field or method Get)"
    )
    out = _fix_uncalled_method_value(written, err)
    assert 'rec.Header().Get("Retry-After")' in out["x_test.go"]
    assert "rec.Header.Get" not in out["x_test.go"]


def test_does_not_touch_request_header_field_on_same_file():
    # req.Header IS a field, so the compiler never flags it — only rec.Header is
    # flagged, and only that line/expression is rewritten.
    written = {
        "x_test.go": (
            "package main\n\nfunc f(req Q, rec R) {\n"
            "\treq.Header.Set(\"X\", \"1\")\n"        # line 4: valid, untouched
            "\t_ = rec.Header.Get(\"X\")\n"           # line 5: flagged
            "}\n"
        )
    }
    err = (
        "./x_test.go:5:13: rec.Header.Get undefined "
        "(type func() http.Header has no field or method Get)"
    )
    out = _fix_uncalled_method_value(written, err)
    body = out["x_test.go"]
    assert "req.Header.Set(\"X\", \"1\")" in body  # request field untouched
    assert "rec.Header().Get(\"X\")" in body       # recorder method called


def test_multiple_flagged_lines_all_fixed():
    written = {
        "x_test.go": (
            "package main\n\nfunc f(rec R) {\n"
            "\ta := rec.Header.Get(\"A\")\n"
            "\tb := rec.Header.Get(\"B\")\n"
            "\t_, _ = a, b\n}\n"
        )
    }
    err = (
        "./x_test.go:4:8: rec.Header.Get undefined (type func() http.Header has no field or method Get)\n"
        "./x_test.go:5:8: rec.Header.Get undefined (type func() http.Header has no field or method Get)"
    )
    body = _fix_uncalled_method_value(written, err)["x_test.go"]
    assert body.count("rec.Header().Get") == 2
    assert "rec.Header.Get" not in body


def test_no_error_no_change():
    assert _fix_uncalled_method_value({"a.go": "package a\n"}, "") == {}


def test_composes_in_deterministic_gate_chain():
    written = {
        "x_test.go": "package main\n\nfunc f(rec R) {\n\t_ = rec.Header.Get(\"X\")\n}\n"
    }
    err = (
        "./x_test.go:4:13: rec.Header.Get undefined "
        "(type func() http.Header has no field or method Get)"
    )
    out = _run_deterministic_gates(written, err, None)
    assert 'rec.Header().Get("X")' in out["x_test.go"]
