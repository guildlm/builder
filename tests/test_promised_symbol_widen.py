"""Root-cause routing for a single-package project.

`undefined: NewStore` is reported in store_test.go — the USE site — so the fix
loop regenerates the test over and over while the real defect is that store.go
named its constructor NewStoreImpl. The spec knows who owed the symbol.
"""

from src.builder import FileSpec, _widen_promised_symbol_targets

FILES = (
    FileSpec(path="task.go", purpose="package main. The Task struct."),
    FileSpec(
        path="store.go",
        purpose="package main. A concrete store built by a constructor named "
        "EXACTLY `NewStore() *Store`.",
    ),
    FileSpec(path="handlers.go", purpose="package main. HTTP handlers over the store."),
    FileSpec(
        path="store_test.go",
        purpose="package main. Tests that call NewStore() and assert round-trips.",
    ),
)

WRITTEN = {
    "task.go": "package main\n\ntype Task struct{ ID int }\n",
    # The model modelled Store as an interface and named the constructor
    # NewStoreImpl — so NewStore, which everything else calls, does not exist.
    "store.go": (
        "package main\n\ntype Store interface{ Get(id int) (Task, error) }\n\n"
        "type StoreImpl struct{}\n\nfunc NewStoreImpl() *StoreImpl "
        "{ return &StoreImpl{} }\n"
    ),
    "handlers.go": "package main\n",
    "store_test.go": "package main\n\nfunc TestX(t *testing.T) { s := NewStore() }\n",
}

ERR = "./store_test.go:3:30: undefined: NewStore"


def test_routes_the_fix_to_the_file_that_promised_the_symbol():
    # The loop starts out targeting only the use site — the test file.
    out = _widen_promised_symbol_targets(["store_test.go"], WRITTEN, ERR, FILES)
    assert "store.go" in out       # the definition site is now in the fix
    assert "store_test.go" in out  # the original target survives
    assert "handlers.go" not in out


def test_noop_when_the_symbol_actually_exists():
    # `undefined: NewStore` with NewStore declared somewhere is a qualification
    # miss for another gate, not a missing declaration.
    written = dict(WRITTEN, **{"store.go": "package main\n\nfunc NewStore() {}\n"})
    assert _widen_promised_symbol_targets(["store_test.go"], written, ERR, FILES) == [
        "store_test.go"
    ]


def test_noop_when_nobody_claims_the_symbol():
    err = "./store_test.go:3:30: undefined: TotallyUnknown"
    assert _widen_promised_symbol_targets(["store_test.go"], WRITTEN, err, FILES) == [
        "store_test.go"
    ]


def test_noop_when_several_files_claim_the_symbol():
    # Ambiguous ownership: routing would be a guess, so it stays out.
    files = FILES + (
        FileSpec(path="other.go", purpose="package main. Also mentions NewStore."),
    )
    assert _widen_promised_symbol_targets(["store_test.go"], WRITTEN, ERR, files) == [
        "store_test.go"
    ]


def test_never_routes_to_a_test_file():
    # store_test.go's purpose mentions NewStore too — it calls it — but a test
    # never OWES a constructor, so it must not be picked as the owner.
    files = (
        FileSpec(
            path="store_test.go",
            purpose="package main. Tests that call NewStore().",
        ),
    )
    assert _widen_promised_symbol_targets(["store_test.go"], WRITTEN, ERR, files) == [
        "store_test.go"
    ]


def test_ignores_an_unexported_undefined_symbol():
    # `undefined: tasks` is a local typo, not a promised declaration — and a
    # purpose that happens to use the word "tasks" in prose must not be dragged
    # into the fix because of it.
    files = FILES + (
        FileSpec(path="svc.go", purpose="package main. Aggregates tasks by status."),
    )
    err = "./store_test.go:9:12: undefined: tasks"
    assert _widen_promised_symbol_targets(["store_test.go"], WRITTEN, err, files) == [
        "store_test.go"
    ]


def test_does_not_duplicate_an_existing_target():
    out = _widen_promised_symbol_targets(
        ["store_test.go", "store.go"], WRITTEN, ERR, FILES
    )
    assert out.count("store.go") == 1
