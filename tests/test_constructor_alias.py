"""The missing-constructor gate.

The spec told store.go, emphatically, to expose a constructor named EXACTLY
NewStore. Across repeated rolls the model wrote a Store interface with a
StoreImpl built by NewStoreImpl instead — and kept writing it even when store.go
was regenerated with `undefined: NewStore` in the fix prompt. The prior does not
move, so the repair has to be provable rather than persuasive: alias the name the
spec promised onto the constructor the model actually declared.
"""

from src.builder import _fix_missing_constructor_alias, _run_deterministic_gates

ERR = (
    "./handlers_test.go:12:24: undefined: NewStore\n"
    "./store_test.go:11:7: undefined: NewStore\n"
)

STORE = """package main

type Store interface {
	Create(t Task) error
}

type StoreImpl struct {
	tasks map[int]Task
}

func NewStoreImpl() *StoreImpl {
	return &StoreImpl{tasks: make(map[int]Task)}
}
"""

WRITTEN = {"store.go": STORE, "store_test.go": "package main\n"}


def test_aliases_the_promised_constructor_onto_the_one_that_exists():
    out = _fix_missing_constructor_alias(WRITTEN, ERR)
    body = out["store.go"]
    assert "func NewStore() *StoreImpl { return NewStoreImpl() }" in body
    assert "func NewStoreImpl() *StoreImpl {" in body  # the original survives
    assert "store_test.go" not in out                  # tests are not touched


def test_noop_when_the_constructor_already_exists():
    written = dict(WRITTEN, **{"store.go": STORE + "\nfunc NewStore() {}\n"})
    assert _fix_missing_constructor_alias(written, ERR) == {}


def test_noop_when_two_constructors_could_be_meant():
    # NewStoreImpl and NewStoreV2 both extend the missing name — picking one
    # would be a guess.
    written = dict(
        WRITTEN,
        **{"store.go": STORE + "\nfunc NewStoreV2() *StoreImpl { return nil }\n"},
    )
    assert _fix_missing_constructor_alias(written, ERR) == {}


def test_noop_when_the_candidate_takes_arguments():
    # There is nothing to pass, so no alias can be written.
    store = STORE.replace(
        "func NewStoreImpl() *StoreImpl {", "func NewStoreImpl(n int) *StoreImpl {"
    )
    assert _fix_missing_constructor_alias({"store.go": store}, ERR) == {}


def test_noop_when_the_candidate_returns_a_tuple():
    store = STORE.replace(
        "func NewStoreImpl() *StoreImpl {", "func NewStoreImpl() (*StoreImpl, error) {"
    )
    assert _fix_missing_constructor_alias({"store.go": store}, ERR) == {}


def test_noop_on_an_unrelated_missing_symbol():
    # NewStore is not a prefix of NewRouter — different thing entirely.
    store = "package main\n\nfunc NewRouter() *Mux { return nil }\n"
    assert _fix_missing_constructor_alias({"store.go": store}, ERR) == {}


def test_noop_without_the_error():
    assert _fix_missing_constructor_alias(WRITTEN, "") == {}


def test_composes_in_the_deterministic_gate_chain():
    out = _run_deterministic_gates(WRITTEN, ERR, None)
    assert "func NewStore() *StoreImpl { return NewStoreImpl() }" in out["store.go"]
