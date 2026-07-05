from src.builder import _fix_fatal_guard, _fix_swapped_error_assignment


def test_swaps_err_and_blank_to_error_last():
    # the workapi shape: Create returns (models.Task, error) but the model
    # captured the pair backwards, so `err` holds the Task
    written = {
        "internal/api/tasks.go": (
            "package api\n\nfunc (h *H) Create() {\n"
            "\tif err, _ := h.svc.Create(r.Context(), t); err != nil {\n"
            "\t\treturn\n\t}\n}\n"
        )
    }
    err = (
        "internal/api/tasks.go:4:45: invalid operation: err != nil "
        "(mismatched types models.Task and untyped nil)"
    )
    out = _fix_swapped_error_assignment(written, err)
    assert "if _, err := h.svc.Create(r.Context(), t); err != nil {" in out[
        "internal/api/tasks.go"
    ]


def test_swap_plain_statement_form():
    written = {
        "a.go": "package a\n\nfunc f() {\n\terr, _ = g()\n\t_ = err == nil\n}\n",
    }
    err = (
        "a.go:5:6: invalid operation: err == nil "
        "(mismatched types T and untyped nil)"
    )
    # flagged line 5 has no assignment to rewrite -> untouched; the gate only
    # rewrites when the flagged LINE carries the swapped assignment
    assert _fix_swapped_error_assignment(written, err) == {}
    err2 = (
        "a.go:4:6: invalid operation: err == nil "
        "(mismatched types T and untyped nil)"
    )
    out = _fix_swapped_error_assignment(written, err2)
    assert "_, err = g()" in out["a.go"]


def test_swap_leaves_named_second_var_alone():
    # `err, task := ...` — the second slot is a real variable; reordering
    # could break its uses, so the gate must not fire
    written = {
        "a.go": (
            "package a\n\nfunc f() {\n"
            "\tif err, task := g(); err != nil {\n\t\t_ = task\n\t}\n}\n"
        )
    }
    err = (
        "a.go:4:39: invalid operation: err != nil "
        "(mismatched types T and untyped nil)"
    )
    assert _fix_swapped_error_assignment(written, err) == {}


def test_fatal_guard_promotes_errorf_before_panicking_index():
    written = {
        "internal/service/service_test.go": (
            "package service\n\nfunc TestX(t *testing.T) {\n"           # 1-3
            "\tif len(enq.Calls) != 1 {\n"                              # 4
            '\t\tt.Errorf("Enqueue() called %d times", len(enq.Calls))\n'  # 5
            "\t}\n"                                                     # 6
            '\tif enq.Calls[0].Type != "task.created" {\n'              # 7
            "\t\tt.Error(\"wrong event\")\n\t}\n}\n"
        )
    }
    err = (
        "panic: runtime error: index out of range [0] with length 0 [recovered]\n"
        "guildlm.dev/workapi/internal/service.TestX.func1(0x14000003880)\n"
        "\t/Users/x/generated/workapi14/internal/service/service_test.go:7 +0x324\n"
    )
    out = _fix_fatal_guard(written, err)
    body = out["internal/service/service_test.go"]
    assert 't.Fatalf("Enqueue() called %d times"' in body
    assert body.count("t.Fatalf(") == 1


def test_fatal_guard_needs_len_condition():
    # an Errorf near the panic that is NOT a length guard must stay put
    written = {
        "a_test.go": (
            "package a\n\nfunc TestX(t *testing.T) {\n"
            '\tif name != "x" {\n\t\tt.Errorf("bad name")\n\t}\n'
            "\t_ = xs[0]\n}\n"
        )
    }
    err = (
        "panic: runtime error: index out of range [0] with length 0\n"
        "\t/tmp/a_test.go:7 +0x1\n"
    )
    assert _fix_fatal_guard(written, err) == {}


def test_fatal_guard_ignores_non_panic_output():
    written = {"a_test.go": "package a\n"}
    assert _fix_fatal_guard(written, "a_test.go:3:1: undefined: x") == {}
