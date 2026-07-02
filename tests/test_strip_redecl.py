from src.builder import strip_redeclarations, top_level_decls

def test_strips_redeclared_var_and_doc_comment():
    sib = 'package main\nimport "errors"\nvar ErrNotFound = errors.New("nf")\n'
    code = ('package main\nimport "errors"\n\n'
            '// ErrNotFound doc\nvar ErrNotFound = errors.New("nf")\n\n'
            'type Store struct{}\n')
    out = strip_redeclarations(code, top_level_decls(sib))
    assert "ErrNotFound" not in top_level_decls(out)
    assert "Store" in top_level_decls(out)
    assert "// ErrNotFound doc" not in out

def test_strips_inside_var_block_and_keeps_others():
    forbidden = {"ErrA"}
    code = 'package main\nvar (\n\tErrA = 1\n\tErrB = 2\n)\n'
    out = strip_redeclarations(code, forbidden)
    assert "ErrA" not in top_level_decls(out)
    assert "ErrB" in top_level_decls(out)

def test_keeps_methods_with_same_name():
    # a method named like a forbidden plain func must NOT be stripped
    forbidden = {"Validate"}
    code = 'package main\nfunc (t Task) Validate() error { return nil }\n'
    out = strip_redeclarations(code, forbidden)
    assert "Validate() error" in out

def test_noop_when_nothing_forbidden():
    code = 'package main\nfunc X() {}\n'
    assert strip_redeclarations(code, set()) == code


from src.builder import exported_api, _dir_of, pkg_name_of, _package_context


def test_dir_of_and_pkg_name():
    assert _dir_of("internal/store/store.go") == "internal/store"
    assert _dir_of("main.go") == ""
    assert pkg_name_of("package store\nfunc X(){}\n") == "store"


def test_exported_api_hides_unexported():
    code = ("package store\n"
            "type Store struct{ x int }\n"
            "func NewStore() *Store { return nil }\n"
            "func (s *Store) internal() {}\n"
            "func unexported() {}\n")
    api = exported_api(code)
    assert "type Store struct" in api
    assert "func NewStore() *Store" in api
    assert "unexported" not in api
    assert "internal" not in api


def test_package_context_splits_same_vs_other():
    written = {
        "internal/store/store.go": "package store\ntype Store struct{}\nfunc NewStore() *Store { return nil }\n",
        "internal/api/handler.go": "package api\nfunc H() {}\n",
    }
    ctx = _package_context(written, "internal/api/router.go", "app.dev/x")
    # same package (api) shown full; other package (store) shown as imported api
    assert "internal/api/handler.go" in ctx
    assert 'import "app.dev/x/internal/store"' in ctx
    assert "func NewStore() *Store" in ctx


def test_strips_multiline_signature_func():
    from src.builder import strip_redeclarations, top_level_decls
    code = (
        "package main\n\n"
        "func Foo(\n\ta int,\n\tb int,\n) int {\n\treturn a + b\n}\n\n"
        "func Keep() {}\n"
    )
    out = strip_redeclarations(code, {"Foo"})
    assert "Foo" not in top_level_decls(out)
    assert "Keep" in top_level_decls(out)
    assert "return a + b" not in out  # body fully removed, not orphaned


def test_requalify_undefined_cross_package():
    from src.builder import _requalify_undefined
    written = {
        "internal/store/store.go": "package store\nimport \"errors\"\nvar ErrExists = errors.New(\"e\")\n",
        "internal/service/service.go": "package service\nfunc F() {}\n",
        "internal/api/tasks.go": "package api\nimport \"guildlm.dev/x/internal/service\"\nfunc h() error { return service.ErrExists }\n",
    }
    err = "internal/api/tasks.go:3:40: undefined: service.ErrExists"
    changed = _requalify_undefined(written, err)
    assert "internal/api/tasks.go" in changed
    assert "store.ErrExists" in changed["internal/api/tasks.go"]
    assert "service.ErrExists" not in changed["internal/api/tasks.go"]
