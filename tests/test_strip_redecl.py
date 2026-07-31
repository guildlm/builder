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


def test_method_decls_extraction():
    from src.builder import method_decls
    code = (
        "package store\n\n"
        "func (s *MemStore) CreateTask(t Task) error { return nil }\n"
        "func (s MemStore) Len() int { return 0 }\n"
        "func (MemStore) Unnamed() {}\n"
        "func (s *Cache[T]) Get(k string) T { var z T; return z }\n"
        "func Plain() {}\n"
    )
    assert method_decls(code) == {
        "MemStore.CreateTask",
        "MemStore.Len",
        "MemStore.Unnamed",
        "Cache.Get",
    }


def test_strips_method_redeclared_by_sibling():
    from src.builder import strip_redeclarations
    # the taskapi-dapt300 failure: store.go re-declares memory.go's MemStore
    # methods -> "method already declared", unrecoverable for the fix loop
    code = (
        "package store\n\n"
        "type Store interface {\n\tCreateTask(t Task) error\n}\n\n"
        "// CreateTask stores a task.\n"
        "func (s *MemStore) CreateTask(t Task) error {\n\treturn nil\n}\n\n"
        "func (s *MemStore) GetTask(id string) (Task, error) {\n\treturn Task{}, nil\n}\n"
    )
    out = strip_redeclarations(code, {"MemStore.CreateTask", "MemStore.GetTask"})
    assert "func (s *MemStore) CreateTask" not in out
    assert "func (s *MemStore) GetTask" not in out
    assert "// CreateTask stores a task." not in out  # doc comment removed too
    assert "type Store interface" in out              # interface untouched
    assert "CreateTask(t Task) error" in out          # ...including its method set


def test_method_name_sharing_across_types_is_kept():
    from src.builder import strip_redeclarations
    # same method NAME on a DIFFERENT receiver is legal Go — must survive
    code = (
        "package store\n\n"
        "func (s *FileStore) CreateTask(t Task) error {\n\treturn nil\n}\n"
    )
    out = strip_redeclarations(code, {"MemStore.CreateTask"})
    assert "func (s *FileStore) CreateTask" in out


def test_gomod_content_deterministic():
    from src.builder import _gomod_content
    assert _gomod_content("guildlm.dev/taskapi") == "module guildlm.dev/taskapi\n\ngo 1.23\n"


# ── what the stripper REMOVED, by name (31 July) ────────────────────────────────────
# Until today both call sites were anonymous: _sample_clean announced that stripping had
# happened without naming a symbol, and _sample_verified_fix printed nothing at all.
# Measured across the archive: 526 events in 276 of 779 log files, every one anonymous,
# and the fix path's count unrecoverable in principle. "The stripper removed what the
# model wrote" is a live hypothesis for the EMPTY-file defect and could not be tested
# against a record that does not name the symbols.

def test_stripped_names_reports_vars_and_methods():
    from src.builder import _stripped_names
    before = ("package x\n\ntype Store interface{}\n\nvar ErrX = 1\n\n"
              "func (m *Mem) Get() {}\n")
    after = "package x\n\ntype Store interface{}\n"
    assert _stripped_names(before, after) == ["ErrX", "Mem.Get"]


def test_stripped_names_is_empty_when_nothing_went():
    from src.builder import _stripped_names
    code = "package x\n\nfunc A() {}\n"
    assert _stripped_names(code, code) == []


def test_stripped_names_does_not_report_additions():
    """A candidate that GAINS a declaration must not report it as removed — the set
    difference runs one way and this pins the direction."""
    from src.builder import _stripped_names
    before = "package x\n\nfunc A() {}\n"
    after = "package x\n\nfunc A() {}\n\nfunc B() {}\n"
    assert _stripped_names(before, after) == []


def test_generation_site_logs_the_names(capsys):
    """Drives the real _sample_clean and reads what it printed. The control is the
    assertion that the NAME appears, not merely that a message did — the old line
    already said stripping had happened."""
    from src.builder import _sample_clean, GoToolchain, FakeCoder
    coder = FakeCoder({"main.go": [
        "```go\npackage main\n\nvar ErrNotFound = 1\n\nfunc main() {}\n```",
    ]})
    _sample_clean(coder, "TARGET_FILE: main.go\n", True, 1, GoToolchain(), "gen",
                  {"ErrNotFound"})
    # _log writes to STDERR, not stdout
    out = capsys.readouterr().err
    assert "stripped redeclared symbols" in out
    assert "ErrNotFound" in out, "the message must NAME the symbol, not just report the event"


def test_fix_site_logs_the_names(tmp_path, capsys):
    """The SECOND call site — _sample_verified_fix — printed nothing at all before today,
    and it is the busier of the two: it runs on every fix candidate inside the loop.

    This drives it with a real (tiny) Go module so the ground-truth gate has something to
    run against. The message must say 'fix' so the two sites stay distinguishable in a log
    that contains both."""
    from src.builder import _sample_verified_fix, GoToolchain, FakeCoder, _write_file

    (tmp_path / "go.mod").write_text("module example.com/m\n\ngo 1.22\n")
    written = {"main.go": _write_file(tmp_path, "main.go", "package main\n\nfunc main() {}\n")}
    coder = FakeCoder({"main.go": [
        "```go\npackage main\n\nvar ErrTaken = 1\n\nfunc main() {}\n```",
    ]})
    _sample_verified_fix(coder, "TARGET_FILE: main.go\n", "main.go", tmp_path, written,
                         1, GoToolchain(), sibling_decls={"ErrTaken"})
    err = capsys.readouterr().err
    assert "stripped redeclared symbols from fix candidate" in err, \
        "the fix path must announce stripping at all -- it was silent before 31 July"
    assert "ErrTaken" in err, "and it must NAME the symbol"
