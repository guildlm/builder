"""Three repairs found by running the gate chain over the ARCHIVED failures.

Keeping the red artifacts (rather than rm -rf'ing them on the next run, as the
harness used to) is what made this possible: the chain can be re-run over every
project the model ever broke, and whatever it still cannot fix is the backlog.
All three of these have exactly one meaning, which is what separates them from a
guess.
"""

from src.builder import (
    _fix_negated_comparison,
    _fix_self_qualified_package,
    _fix_slice_equal,
    _run_deterministic_gates,
)


# ---------------------------------------------------------------- self-qualifier

SELF_QUAL = """package store

import (
	"context"
	"testing"
)

func TestX(t *testing.T) {
	s := NewMemStore()
	if _, err := s.GetTask(context.Background(), "x"); err != store.ErrNotFound {
		t.Fatal(err)
	}
}
"""

STORE_IMPL = (
    "package store\n\nimport \"errors\"\n\nvar ErrNotFound = errors.New(\"not found\")\n"
    "\ntype MemStore struct{}\n\nfunc NewMemStore() *MemStore { return &MemStore{} }\n"
)


def test_a_package_never_qualifies_its_own_symbols():
    """`store.ErrNotFound` inside `package store`. There is nothing named `store`
    in scope — a package cannot import itself — so the compiler reports the
    QUALIFIER as undefined. Dropping it is the only thing it could have meant."""
    written = {"store/memory_test.go": SELF_QUAL, "store/store.go": STORE_IMPL}
    err = "./store/memory_test.go:10:47: undefined: store"
    body = _fix_self_qualified_package(written, err)["store/memory_test.go"]
    assert "err != ErrNotFound" in body
    assert "store.ErrNotFound" not in body
    assert len(body.splitlines()) == len(SELF_QUAL.splitlines())  # phase one


def test_it_leaves_a_symbol_the_package_does_not_declare():
    # `store.Missing` is not ours to rename — dropping the qualifier would invent
    # a symbol rather than fix one.
    src = SELF_QUAL.replace("store.ErrNotFound", "store.Missing")
    written = {"store/memory_test.go": src, "store/store.go": STORE_IMPL}
    err = "./store/memory_test.go:10:47: undefined: store"
    assert _fix_self_qualified_package(written, err) == {}


# ------------------------------------------------------------- !x == y on a string

def test_a_bang_on_a_non_bool_can_only_have_meant_not_equal():
    """`if !x.Error() == "not found"` parses as `(!x) == y`, and `!` is not
    defined on a string — so the line could never have compiled, and there is no
    working program whose meaning we might be changing. Both readings of what was
    meant — `!(x == y)` and "x is not y" — are `x != y`."""
    code = (
        "package store\n\nfunc f() {\n"
        '\tif !tt.getWant.Error() == "not found" {\n\t}\n}\n'
    )
    err = (
        "./p.go:4:5: invalid operation: operator ! not defined on "
        "tt.getWant.Error() (value of type string)"
    )
    body = _fix_negated_comparison({"p.go": code}, err)["p.go"]
    assert 'tt.getWant.Error() != "not found"' in body
    assert "!tt.getWant" not in body
    assert len(body.splitlines()) == len(code.splitlines())  # phase one


# ------------------------------------------------------------------- slice.Equal

def test_a_slice_has_no_equal_method():
    """The model reached for `.Equal` because most languages have it. The compiler
    prints the receiver's type, so we KNOW it is a slice, and Go has exactly one
    standard way to compare two: reflect.DeepEqual."""
    code = (
        "package store\n\nimport \"testing\"\n\nfunc TestX(t *testing.T) {\n"
        "\tif !tt.listWant.Equal(got) {\n\t\tt.Fatal(\"nope\")\n\t}\n}\n"
    )
    err = (
        "./p.go:6:19: tt.listWant.Equal undefined "
        "(type []models.Task has no field or method Equal)"
    )
    body = _fix_slice_equal({"p.go": code}, err)["p.go"]
    assert "reflect.DeepEqual(tt.listWant, got)" in body
    assert '"reflect"' in body        # and the import it needs


def test_slice_equal_composes_in_the_chain():
    code = (
        "package store\n\nimport \"testing\"\n\nfunc TestX(t *testing.T) {\n"
        "\tif !tt.listWant.Equal(got) {\n\t\tt.Fatal(\"nope\")\n\t}\n}\n"
    )
    err = (
        "./p.go:6:19: tt.listWant.Equal undefined "
        "(type []models.Task has no field or method Equal)"
    )
    out = _run_deterministic_gates({"p.go": code}, err, None)
    assert "reflect.DeepEqual(tt.listWant, got)" in out["p.go"]
