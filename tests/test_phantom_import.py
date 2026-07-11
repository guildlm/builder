from src.builder import _fix_phantom_local_import

ERR = (
    "internal/api/router.go:8:2: no required module provides package "
    "guildlm.dev/workapi/internal/middleware; to add it:\n"
    "\tgo get guildlm.dev/workapi/internal/middleware"
)


def test_same_package_symbols_drop_import_and_qualifier():
    # the workapi21 shape: middleware.Chain/Logging live in the SAME package
    written = {
        "internal/api/router.go": (
            "package api\n\nimport (\n"
            '\t"net/http"\n\n'
            '\t"guildlm.dev/workapi/internal/middleware"\n'
            ")\n\n"
            "func NewRouter() http.Handler {\n"
            "\tmux := http.NewServeMux()\n"
            "\treturn middleware.Chain(mux, middleware.Logging(nil))\n"
            "}\n"
        ),
        "internal/api/middleware.go": (
            "package api\n\nimport \"net/http\"\n\n"
            "type Middleware func(http.Handler) http.Handler\n\n"
            "func Chain(h http.Handler, mws ...Middleware) http.Handler { return h }\n\n"
            "func Logging(l any) Middleware { return nil }\n"
        ),
    }
    out = _fix_phantom_local_import(written, ERR, "guildlm.dev/workapi")
    body = out["internal/api/router.go"]
    assert "internal/middleware" not in body
    assert "Chain(mux, Logging(nil))" in body
    assert "middleware." not in body


def test_other_package_symbols_rewrite_import_and_qualifier():
    written = {
        "internal/api/router.go": (
            "package api\n\nimport (\n"
            '\t"net/http"\n\n'
            '\t"guildlm.dev/workapi/internal/middleware"\n'
            ")\n\n"
            "func NewRouter() http.Handler {\n"
            "\treturn middleware.TokenAuth(\"x\")(http.NewServeMux())\n"
            "}\n"
        ),
        "internal/auth/auth.go": (
            "package auth\n\nimport \"net/http\"\n\n"
            "func TokenAuth(token string) func(http.Handler) http.Handler "
            "{ return nil }\n"
        ),
    }
    out = _fix_phantom_local_import(written, ERR, "guildlm.dev/workapi")
    body = out["internal/api/router.go"]
    assert '"guildlm.dev/workapi/internal/auth"' in body
    assert "auth.TokenAuth" in body
    assert "middleware." not in body


def test_ambiguous_or_unknown_symbols_left_alone():
    # no project package declares middleware.Whatever -> the model's call
    written = {
        "internal/api/router.go": (
            "package api\n\n"
            'import "guildlm.dev/workapi/internal/middleware"\n\n'
            "var _ = middleware.Whatever\n"
        ),
        "internal/auth/auth.go": "package auth\n\nfunc TokenAuth() {}\n",
    }
    assert _fix_phantom_local_import(written, ERR, "guildlm.dev/workapi") == {}


def test_existing_package_is_not_touched():
    # the directory exists -> go.mod problem, not a phantom import
    written = {
        "internal/api/router.go": (
            "package api\n\n"
            'import "guildlm.dev/workapi/internal/middleware"\n\n'
            "var _ = middleware.Chain\n"
        ),
        "internal/middleware/mw.go": "package middleware\n\nfunc Chain() {}\n",
    }
    assert _fix_phantom_local_import(written, ERR, "guildlm.dev/workapi") == {}


def test_a_stdlib_package_with_the_module_path_glued_on():
    """The most natural version of this mistake: the model writes
    "guildlm.dev/workapi/internal/slog" when it means "log/slog". Its symbols
    (slog.New, slog.NewTextHandler) live in NO project package, so the owner
    search finds nothing and the gate used to give up — and workapi failed a
    sweep on it. But the phantom's last segment names a stdlib package, and the
    path is simply the real one with a module glued to its front."""
    code = (
        'package worker\n\n'
        'import (\n\t"testing"\n\n\t"guildlm.dev/workapi/internal/slog"\n)\n\n'
        'func TestX(t *testing.T) {\n'
        '\tlogger := slog.New(slog.NewTextHandler(nil, nil))\n'
        '\t_ = logger\n'
        '}\n'
    )
    err = (
        "internal/worker/worker_test.go:6:2: no required module provides package "
        "guildlm.dev/workapi/internal/slog; to add it:"
    )
    out = _fix_phantom_local_import(
        {"internal/worker/worker_test.go": code}, err, "guildlm.dev/workapi"
    )
    body = out["internal/worker/worker_test.go"]
    assert '"log/slog"' in body
    assert "guildlm.dev/workapi/internal/slog" not in body
    assert "slog.New(" in body   # the qualifier was already right
