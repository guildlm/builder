from src.builder import _fix_struct_literal_key

# Verbatim from the held-out ledger run (fix rounds 2 AND 3 — the model could not
# repair it either time, which is what earned this gate).
ERR = "internal/service/service.go:18:17: unknown field s in struct literal of type Ledger"

LEDGER = (
    "package service\n\n"
    'import "guildlm.dev/ledger/internal/store"\n\n'
    "type Ledger struct {\n"
    "\tstore store.Store\n"
    "}\n\n"
    "func NewLedger(s store.Store) *Ledger {\n"
    "\treturn &Ledger{s: s}\n"
    "}\n"
)


def _err(line: int, field: str, typ: str, path: str = "a.go") -> str:
    return f"{path}:{line}:17: unknown field {field} in struct literal of type {typ}"


def test_single_field_key_is_renamed_to_the_field():
    written = {"internal/service/service.go": LEDGER}
    out = _fix_struct_literal_key(written, ERR.replace(":18:", ":10:"))
    body = out["internal/service/service.go"]
    assert "return &Ledger{store: s}" in body
    assert "{s: s}" not in body
    # the declaration is untouched — we rename the key, never add a field
    assert "\tstore store.Store\n" in body
    assert len(body.splitlines()) == len(LEDGER.splitlines())


def test_multi_field_resolves_by_parameter_type():
    code = (
        "package service\n\n"
        "type Ledger struct {\n"
        "\tname  string\n"
        "\tstore store.Store\n"
        "}\n\n"
        "func NewLedger(s store.Store) *Ledger {\n"
        "\treturn &Ledger{s: s}\n"
        "}\n"
    )
    out = _fix_struct_literal_key({"a.go": code}, _err(9, "s", "Ledger"))
    assert "&Ledger{store: s}" in out["a.go"]
    assert "\tname  string\n" in out["a.go"]


def test_multi_field_ambiguous_type_is_left_for_the_model():
    # two fields of the SAME type: nothing in the source says which one was meant
    code = (
        "package service\n\n"
        "type Pair struct {\n"
        "\tleft  store.Store\n"
        "\tright store.Store\n"
        "}\n\n"
        "func NewPair(s store.Store) *Pair {\n"
        "\treturn &Pair{s: s}\n"
        "}\n"
    )
    assert _fix_struct_literal_key({"a.go": code}, _err(9, "s", "Pair")) == {}


def test_line_the_compiler_named_must_carry_the_key():
    # a stale line number must never make the gate rewrite an innocent line
    out = _fix_struct_literal_key({"a.go": LEDGER}, _err(6, "s", "Ledger"))
    assert out == {}


def test_anonymous_table_struct_is_not_this_gates_business():
    # The sibling class, and it must stay separate: there the anonymous decl is MISSING
    # a field and _fix_unknown_struct_fields ADDS one. Here the field exists and the KEY
    # is wrong. Adding `want` to a named struct would be a second bug, so this gate's
    # regex requires a NAMED type and must stay silent on `struct{...}`.
    err = "a.go:5:20: unknown field want in struct literal of type struct{name string}"
    code = (
        "package a\n\n"
        "func TestX(t *testing.T) {\n"
        "\tcases := []struct{ name string }{\n"
        '\t\t{name: "x", want: 1},\n'
        "\t}\n"
        "}\n"
    )
    assert _fix_struct_literal_key({"a.go": code}, err) == {}
