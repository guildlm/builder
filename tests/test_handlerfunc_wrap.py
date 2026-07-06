from src.builder import _fix_handlerfunc_wrap


def test_wraps_raw_handler_func_at_use_site():
    # verbatim compiler error from the ratelimit farm runs: PingHandler was
    # declared as a plain func and passed where http.Handler is expected.
    written = {
        "api.go": (
            "package main\n\n"
            'import "net/http"\n\n'
            "func NewRouter(reg *Registry) http.Handler {\n"
            "\tmux := http.NewServeMux()\n"
            '\tmux.Handle("GET /ping", RateLimit(reg)(PingHandler))\n'
            "\treturn mux\n"
            "}\n"
        ),
    }
    err = (
        "./api.go:7:41: cannot use PingHandler (value of type func(w "
        "http.ResponseWriter, r *http.Request)) as http.Handler value in "
        "argument to RateLimit(reg): func(w http.ResponseWriter, r "
        "*http.Request) does not implement http.Handler (missing method "
        "ServeHTTP)"
    )
    out = _fix_handlerfunc_wrap(written, err)
    assert "RateLimit(reg)(http.HandlerFunc(PingHandler))" in out["api.go"]


def test_wraps_dotted_method_value():
    written = {
        "router.go": (
            "package main\n\n"
            'import "net/http"\n\n'
            "func routes(h *Handler) {\n"
            '\thttp.Handle("/x", h.Create)\n'
            "}\n"
        ),
    }
    err = (
        "./router.go:6:20: cannot use h.Create (value of type "
        "func(http.ResponseWriter, *http.Request)) as http.Handler value in "
        "argument to http.Handle: func(http.ResponseWriter, *http.Request) "
        "does not implement http.Handler (missing method ServeHTTP)"
    )
    out = _fix_handlerfunc_wrap(written, err)
    assert 'http.Handle("/x", http.HandlerFunc(h.Create))' in out["router.go"]


def test_non_handler_func_left_alone():
    # a mismatched func whose type does NOT mention ResponseWriter is a real
    # bug for the model, not a mechanical wrap.
    written = {"a.go": "package main\n\nvar _ = take(Worker)\n"}
    err = (
        "./a.go:3:14: cannot use Worker (value of type func(int) error) as "
        "http.Handler value in argument to take: func(int) error does not "
        "implement http.Handler (missing method ServeHTTP)"
    )
    assert _fix_handlerfunc_wrap(written, err) == {}


def test_already_wrapped_is_not_double_wrapped():
    written = {
        "api.go": (
            "package main\n\n"
            'import "net/http"\n\n'
            "func routes() {\n"
            '\thttp.Handle("/p", http.HandlerFunc(PingHandler))\n'
            "}\n"
        ),
    }
    err = (
        "./api.go:6:38: cannot use PingHandler (value of type func(w "
        "http.ResponseWriter, r *http.Request)) as http.Handler value in "
        "argument to http.Handle: func(w http.ResponseWriter, r *http.Request) "
        "does not implement http.Handler (missing method ServeHTTP)"
    )
    assert _fix_handlerfunc_wrap(written, err) == {}


def test_call_expression_is_not_wrapped():
    # PingHandler() is a CALL — wrapping the call result cannot fix the
    # interface mismatch; leave it for the model.
    written = {
        "api.go": (
            "package main\n\n"
            "func routes() {\n"
            '\thandle("/p", PingHandler())\n'
            "}\n"
        ),
    }
    err = (
        "./api.go:4:15: cannot use PingHandler (value of type func(w "
        "http.ResponseWriter, r *http.Request)) as http.Handler value in "
        "argument to handle: func(w http.ResponseWriter, r *http.Request) "
        "does not implement http.Handler (missing method ServeHTTP)"
    )
    assert _fix_handlerfunc_wrap(written, err) == {}
