from src.builder import _fix_unused_var, _run_deterministic_gates


def test_blanks_unused_name_in_multi_assign():
    # the shortener case: value captured only to validate, never read
    written = {
        "handlers.go": (
            "package main\n\nimport \"net/url\"\n\n"
            "func h(raw string) error {\n"
            "\tu, err := url.ParseRequestURI(raw)\n"
            "\tif err != nil {\n\t\treturn err\n\t}\n"
            "\treturn nil\n}\n"
        )
    }
    err = "./handlers.go:6:2: declared and not used: u"
    out = _fix_unused_var(written, err)
    body = out["handlers.go"]
    assert "\t_, err := url.ParseRequestURI(raw)\n" in body
    assert "u, err :=" not in body
    # err is still a `:=` new var, so the short-decl form is kept
    assert ":=" in body


def test_lone_unused_var_left_for_model():
    # `u := f()` alone -> the value was likely meant to be used; blanking would
    # mask that, so the gate abstains and the model regenerates the line.
    written = {"a.go": "package a\n\nfunc f() int { return 1 }\n\nfunc g() {\n\tu := f()\n}\n"}
    err = "./a.go:6:2: declared and not used: u"
    assert _fix_unused_var(written, err) == {}


def test_var_decl_left_for_model():
    # not a `:=` short decl -> gate abstains
    written = {"a.go": "package a\n\nfunc g() {\n\tvar u int\n}\n"}
    err = "./a.go:4:6: declared and not used: u"
    assert _fix_unused_var(written, err) == {}


def test_name_not_on_lhs_skipped():
    # defensive: if the flagged name isn't found on the `:=` LHS, don't guess
    written = {"a.go": "package a\n\nfunc g() {\n\tx, err := f()\n\t_ = x\n}\n"}
    err = "./a.go:4:2: declared and not used: zzz"
    assert _fix_unused_var(written, err) == {}


def test_word_boundary_does_not_touch_url_import_usage():
    # blanking `u` must not corrupt `url` on the RHS
    written = {
        "h.go": (
            "package main\n\nimport \"net/url\"\n\n"
            "func h(raw string) {\n\tu, err := url.Parse(raw)\n\t_ = err\n}\n"
        )
    }
    err = "./h.go:6:2: declared and not used: u"
    body = _fix_unused_var(written, err)["h.go"]
    assert "url.Parse(raw)" in body  # RHS untouched
    assert "\t_, err := url.Parse(raw)\n" in body


def test_no_error_no_change():
    assert _fix_unused_var({"a.go": "package a\n"}, "") == {}


def test_composes_in_deterministic_gate_chain():
    written = {
        "handlers.go": (
            "package main\n\nimport \"net/url\"\n\n"
            "func h(raw string) error {\n"
            "\tu, err := url.ParseRequestURI(raw)\n"
            "\tif err != nil {\n\t\treturn err\n\t}\n\treturn nil\n}\n"
        )
    }
    err = "./handlers.go:6:2: declared and not used: u"
    out = _run_deterministic_gates(written, err, None)
    assert "\t_, err := url.ParseRequestURI(raw)\n" in out["handlers.go"]
