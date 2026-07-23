"""Three repairs found by running the gate chain over the ARCHIVED failures.

Keeping the red artifacts (rather than rm -rf'ing them on the next run, as the
harness used to) is what made this possible: the chain can be re-run over every
project the model ever broke, and whatever it still cannot fix is the backlog.
All three of these have exactly one meaning, which is what separates them from a
guess.
"""

from src.builder import (
    _fix_external_test_package,
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


def test_a_bare_negation_with_no_comparison_is_left_for_the_model():
    # `if !x.Error() {` is `!string` with no `== rhs`. The gate only rewrites the
    # `!x == y` comparison form; a bare negation is a different bug it must not
    # touch (there is no comparison whose sense to flip).
    code = "package store\n\nfunc f() {\n\tif !tt.getWant.Error() {\n\t}\n}\n"
    err = (
        "./p.go:4:5: invalid operation: operator ! not defined on "
        "tt.getWant.Error() (value of type string)"
    )
    assert _fix_negated_comparison({"p.go": code}, err) == {}


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


def test_equal_on_a_non_slice_type_is_left_alone():
    # reflect.DeepEqual is the answer only because the receiver is a SLICE. `.Equal`
    # undefined on a struct is a different problem (the type may want its own Equal),
    # so the gate's regex requires a []T receiver and must not fire here.
    code = "package store\n\nfunc f() {\n\tif !x.Equal(y) {\n\t}\n}\n"
    err = (
        "./p.go:4:6: x.Equal undefined "
        "(type MyStruct has no field or method Equal)"
    )
    assert _fix_slice_equal({"p.go": code}, err) == {}


# ------------------------------------------------ external test package + bare symbol

STRINGKIT_IMPL = (
    "package stringkit\n\n"
    "func Reverse(s string) string { return s }\n\n"
    "func IsPalindrome(s string) bool { return true }\n"
)

EXT_TEST_BARE = """package stringkit_test

import "testing"

func TestReverse(t *testing.T) {
	if Reverse("abc") != "cba" {
		t.Fatal("bad")
	}
}
"""


def test_external_test_package_using_bare_symbol_switches_to_internal():
    """`package stringkit_test` calling bare `Reverse` is undefined — an external test
    package must qualify (`stringkit.Reverse`). The bare call means the model wanted the
    internal test package, so drop the `_test` suffix from the clause."""
    written = {"stringkit.go": STRINGKIT_IMPL, "stringkit_test.go": EXT_TEST_BARE}
    err = "./stringkit_test.go:6:5: undefined: Reverse"
    out = _fix_external_test_package(written, err)
    assert "stringkit_test.go" in out
    body = out["stringkit_test.go"]
    assert body.startswith("package stringkit\n")
    assert "package stringkit_test" not in body
    assert len(body.splitlines()) == len(EXT_TEST_BARE.splitlines())  # line-preserving


def test_correctly_qualified_external_test_is_untouched():
    # `stringkit.Reverse` is valid in an external test package — no bare undefined, so the
    # gate must not fire (and there'd be no such error anyway).
    qualified = EXT_TEST_BARE.replace("Reverse(", "stringkit.Reverse(").replace(
        'import "testing"', 'import (\n\t"testing"\n\n\t"x/stringkit"\n)')
    written = {"stringkit.go": STRINGKIT_IMPL, "stringkit_test.go": qualified}
    assert _fix_external_test_package(written, "") == {}


def test_does_not_invent_a_symbol_the_package_lacks():
    # `undefined: Missing` — not declared in package stringkit, so switching to internal
    # would not resolve it; the gate must refuse rather than mask a real bug.
    src = EXT_TEST_BARE.replace("Reverse", "Missing")
    written = {"stringkit.go": STRINGKIT_IMPL, "stringkit_test.go": src}
    err = "./stringkit_test.go:6:5: undefined: Missing"
    assert _fix_external_test_package(written, err) == {}


def test_only_the_file_the_error_names():
    # A second, correct external test in the same dir must not be rewritten just because a
    # sibling triggered — the gate keys on the file the compiler named.
    other = "package stringkit_test\n\nimport \"testing\"\n\nfunc TestOther(t *testing.T) {}\n"
    written = {
        "stringkit.go": STRINGKIT_IMPL,
        "stringkit_test.go": EXT_TEST_BARE,
        "other_test.go": other,
    }
    err = "./stringkit_test.go:6:5: undefined: Reverse"
    out = _fix_external_test_package(written, err)
    assert set(out) == {"stringkit_test.go"}  # other_test.go left alone
