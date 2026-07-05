from src.builder import _fix_if_composite_literal

HINT = (
    "expected boolean expression, found assignment "
    "(missing parentheses around composite literal?)"
)


def test_wraps_literal_in_if_header():
    # the workapi8 shape: got/want short decl with a struct literal in the init
    written = {
        "internal/service/service_test.go": (
            "package service\n\nfunc TestX(t *testing.T) {\n"
            '\tif got, want := tk, models.Task{ID: "1", Title: "t"}; got != want {\n'
            "\t\tt.Errorf(\"got %v want %v\", got, want)\n"
            "\t}\n"
            "}\n"
        )
    }
    err = f"internal/service/service_test.go:4:5: {HINT}"
    out = _fix_if_composite_literal(written, err)
    body = out["internal/service/service_test.go"]
    assert (
        'if got, want := tk, (models.Task{ID: "1", Title: "t"}); got != want {'
        in body
    )


def test_fixes_every_header_in_flagged_file_at_once():
    # the parser reports one syntax error at a time; fixing the whole file
    # saves a round per occurrence
    written = {
        "a_test.go": (
            "package a\n\nfunc TestX(t *testing.T) {\n"
            "\tif got, want := f(), Event{Type: \"x\"}; got != want {\n"
            "\t}\n"
            "\tif got, want := g(), models.Event{Type: \"y\"}; got != want {\n"
            "\t}\n"
            "}\n"
        )
    }
    err = f"a_test.go:4:5: {HINT}"
    out = _fix_if_composite_literal(written, err)
    body = out["a_test.go"]
    assert '(Event{Type: "x"})' in body
    assert '(models.Event{Type: "y"})' in body


def test_block_open_brace_is_not_a_literal():
    # `want {` at the end of the header must never be wrapped (lowercase)
    written = {
        "a_test.go": (
            "package a\n\nfunc TestX(t *testing.T) {\n"
            "\tif got != want {\n\t}\n}\n"
        )
    }
    err = f"a_test.go:4:5: {HINT}"
    assert _fix_if_composite_literal(written, err) == {}


def test_already_parenthesized_literal_untouched():
    written = {
        "a_test.go": (
            "package a\n\nfunc TestX(t *testing.T) {\n"
            "\tif got, want := f(), (Event{Type: \"x\"}); got != want {\n"
            "\t}\n"
            "}\n"
        )
    }
    err = f"a_test.go:4:5: {HINT}"
    assert _fix_if_composite_literal(written, err) == {}


def test_plain_assignment_error_without_hint_left_to_model():
    # `if x = 5; ...` is a REAL bug, not the parenthesization slip
    written = {
        "a.go": "package a\n\nfunc g() {\n\tif x = 5; x > 0 {\n\t}\n}\n",
    }
    err = "a.go:4:5: expected boolean expression, found assignment"
    assert _fix_if_composite_literal(written, err) == {}


def test_nested_braces_scan_balanced():
    written = {
        "a_test.go": (
            "package a\n\nfunc TestX(t *testing.T) {\n"
            "\tif got, want := f(), Resp{Items: []Item{{ID: 1}}}; got != want {\n"
            "\t}\n"
            "}\n"
        )
    }
    err = f"a_test.go:4:5: {HINT}"
    out = _fix_if_composite_literal(written, err)
    assert "(Resp{Items: []Item{{ID: 1}}})" in out["a_test.go"]
