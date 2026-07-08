from src.builder import _fix_middleware_arity, _rewrite_middleware_def

# The verbatim residual that stalled BOTH the v4 champion and the v5 model on
# workapi: middleware constructors defined with the next handler as their first
# parameter, yet called as Recover(logger) and passed to a Chain(h, ...Middleware).
_MIDDLEWARE_GO = (
    "package api\n\n"
    "import (\n"
    '\t"log/slog"\n'
    '\t"net/http"\n'
    ")\n\n"
    "type Middleware func(http.Handler) http.Handler\n\n"
    "func Chain(h http.Handler, mws ...Middleware) http.Handler {\n"
    "\tfor i := len(mws) - 1; i >= 0; i-- {\n"
    "\t\th = mws[i](h)\n"
    "\t}\n"
    "\treturn h\n"
    "}\n\n"
    "func Logging(next http.Handler, logger *slog.Logger) http.Handler {\n"
    "\treturn http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {\n"
    '\t\tlogger.Info("request", "method", r.Method)\n'
    "\t\tnext.ServeHTTP(w, r)\n"
    "\t})\n"
    "}\n\n"
    "func Recover(next http.Handler, logger *slog.Logger) http.Handler {\n"
    "\treturn http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {\n"
    "\t\tdefer func() {\n"
    "\t\t\tif rec := recover(); rec != nil {\n"
    "\t\t\t\tw.WriteHeader(http.StatusInternalServerError)\n"
    "\t\t\t}\n"
    "\t\t}()\n"
    "\t\tnext.ServeHTTP(w, r)\n"
    "\t})\n"
    "}\n"
)

_ERR = (
    "internal/api/router.go:31:45: not enough arguments in call to Recover\n"
    "\thave (*slog.Logger)\n"
    "\twant (http.Handler, *slog.Logger)\n"
    "internal/api/router.go:31:33: not enough arguments in call to Logging\n"
    "\thave (*slog.Logger)\n"
    "\twant (http.Handler, *slog.Logger)\n"
)


def test_rewrites_both_middleware_constructors():
    written = {"internal/api/middleware.go": _MIDDLEWARE_GO}
    out = _fix_middleware_arity(written, _ERR)
    fixed = out["internal/api/middleware.go"]
    # config-in / Middleware-out shape, both constructors
    assert "func Recover(logger *slog.Logger) Middleware {" in fixed
    assert "func Logging(logger *slog.Logger) Middleware {" in fixed
    # the next handler moved into the returned closure
    assert fixed.count("return func(next http.Handler) http.Handler {") == 2
    # original bodies preserved
    assert "next.ServeHTTP(w, r)" in fixed
    assert "w.WriteHeader(http.StatusInternalServerError)" in fixed
    # the broken 2-arg definition is gone
    assert "func Recover(next http.Handler, logger *slog.Logger)" not in fixed
    # braces stay balanced
    assert fixed.count("{") == fixed.count("}")


def test_braces_balanced_and_gofmt_parses():
    # a rewrite that doesn't parse would leave raw text that fails to compile;
    # the least we can assert without a Go toolchain is token/brace integrity.
    fixed = _rewrite_middleware_def(_MIDDLEWARE_GO, "Recover")
    assert fixed.count("{") == fixed.count("}")
    assert fixed.count("(") == fixed.count(")")
    assert "func Recover(logger *slog.Logger) Middleware {" in fixed
    assert "func(next http.Handler) http.Handler {" in fixed


def test_not_fired_without_middleware_type():
    # same-looking func, but the file never declares the Middleware shape: a
    # genuine two-arg http.Handler helper — do NOT touch it.
    plain = (
        "package api\n\n"
        'import "net/http"\n\n'
        "func WithLog(next http.Handler, tag string) http.Handler {\n"
        "\treturn next\n"
        "}\n"
    )
    err = (
        "a.go:9:9: not enough arguments in call to WithLog\n"
        "\thave (string)\n"
        "\twant (http.Handler, string)\n"
    )
    assert _fix_middleware_arity({"a.go": plain}, err) == {}


def test_not_fired_without_matching_error():
    # no arity error in the output -> no-op even if the file has the pattern.
    assert _fix_middleware_arity({"internal/api/middleware.go": _MIDDLEWARE_GO}, "") == {}


def test_first_param_must_be_http_handler():
    # want (T, http.Handler) rather than (http.Handler, T) is a different bug;
    # the gate only fires when the FIRST param is the next handler.
    code = (
        "package api\n\n"
        'import "net/http"\n\n'
        "type Middleware func(http.Handler) http.Handler\n\n"
        "func Odd(cfg string, next http.Handler) http.Handler {\n"
        "\treturn next\n"
        "}\n"
    )
    # _MW_ARITY_RE only matches want(http.Handler, ...), so a want(string,...)
    # error never triggers; assert the rewrite helper also refuses this shape.
    assert _rewrite_middleware_def(code, "Odd") == code


def test_missing_config_param_left_alone():
    # func F(next http.Handler) http.Handler is already the decorator shape with
    # no config to hoist; nothing to rewrite.
    code = (
        "package api\n\n"
        'import "net/http"\n\n'
        "type Middleware func(http.Handler) http.Handler\n\n"
        "func Passthrough(next http.Handler) http.Handler {\n"
        "\treturn next\n"
        "}\n"
    )
    assert _rewrite_middleware_def(code, "Passthrough") == code
