from src.builder import _fix_handle_vs_handlefunc

ERR_HANDLER_TO_HANDLEFUNC = (
    "internal/api/router.go:6:32: cannot use "
    "auth.TokenAuth(authToken)(http.HandlerFunc(taskHandler.Create)) "
    "(value of interface type http.Handler) as "
    "func(http.ResponseWriter, *http.Request) value in argument to "
    "mux.HandleFunc"
)


def test_wrapped_handler_switches_to_handle():
    written = {
        "internal/api/router.go": (
            "package api\n\nimport \"net/http\"\n\n"
            "func NewRouter() {\n"
            '\tmux.HandleFunc("POST /tasks", auth.TokenAuth(authToken)(http.HandlerFunc(taskHandler.Create)))\n'
            "}\n"
        )
    }
    out = _fix_handle_vs_handlefunc(written, ERR_HANDLER_TO_HANDLEFUNC)
    body = out["internal/api/router.go"]
    assert 'mux.Handle("POST /tasks", auth.TokenAuth' in body
    assert "mux.HandleFunc(" not in body


def test_bare_func_switches_to_handlefunc():
    err = (
        "a.go:4:20: cannot use h (value of type "
        "func(http.ResponseWriter, *http.Request)) as http.Handler value "
        "in argument to mux.Handle"
    )
    written = {
        "a.go": (
            "package a\n\nfunc f() {\n"
            '\tmux.Handle("/x", h)\n'
            "}\n"
        )
    }
    out = _fix_handle_vs_handlefunc(written, err)
    assert 'mux.HandleFunc("/x", h)' in out["a.go"]


def test_unrelated_type_errors_untouched():
    err = "a.go:4:20: cannot use x (value of type int) as string value in argument to f"
    written = {"a.go": "package a\n\nfunc g() {\n\tf(x)\n}\n"}
    assert _fix_handle_vs_handlefunc(written, err) == {}
