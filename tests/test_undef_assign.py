from src.builder import _fix_undefined_assignment


def test_promotes_plain_assign_to_short_decl():
    # the workapi8 shape: `_, err = ...` inside a fresh t.Run closure where err
    # was only ever declared in a SIBLING closure
    written = {
        "internal/store/memory_test.go": (
            "package store\n\nfunc TestX(t *testing.T) {\n"
            '\t_, err = s.GetTask(context.Background(), "1")\n'
            "\tif !errors.Is(err, ErrNotFound) {\n"
            "\t\tt.Fatal(err)\n"
            "\t}\n"
            "}\n"
        )
    }
    err = "internal/store/memory_test.go:4:5: undefined: err"
    out = _fix_undefined_assignment(written, err)
    body = out["internal/store/memory_test.go"]
    assert '_, err := s.GetTask(context.Background(), "1")' in body


def test_handles_if_prefixed_assignment():
    written = {
        "a_test.go": (
            "package a\n\nfunc TestX(t *testing.T) {\n"
            "\tif err = f(); err != nil {\n\t\tt.Fatal(err)\n\t}\n}\n"
        )
    }
    err = "a_test.go:4:5: undefined: err"
    out = _fix_undefined_assignment(written, err)
    assert "if err := f(); err != nil {" in out["a_test.go"]


def test_leaves_selector_lhs_alone():
    # `x.f = v` cannot become a short var decl — not ours to touch
    written = {
        "a.go": "package a\n\nfunc g() {\n\tx.f, err = f()\n}\n",
    }
    err = "a.go:4:7: undefined: err"
    assert _fix_undefined_assignment(written, err) == {}


def test_leaves_non_assignment_use_alone():
    # undefined name USED but not assigned on the flagged line -> model's call
    written = {
        "a.go": "package a\n\nfunc g() {\n\tif errors.Is(err, ErrX) {\n\t}\n}\n",
    }
    err = "a.go:4:15: undefined: err"
    assert _fix_undefined_assignment(written, err) == {}


def test_ignores_comparison_operators():
    # `==` on the flagged line is not an assignment
    written = {
        "a.go": "package a\n\nfunc g() {\n\t_ = err == nil\n}\n",
    }
    err = "a.go:4:6: undefined: err"
    assert _fix_undefined_assignment(written, err) == {}


def test_idempotent_on_already_fixed_line():
    written = {
        "a.go": "package a\n\nfunc g() {\n\t_, err := f()\n}\n",
    }
    err = "a.go:4:5: undefined: err"
    assert _fix_undefined_assignment(written, err) == {}
