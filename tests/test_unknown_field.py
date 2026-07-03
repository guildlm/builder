"""_fix_unknown_struct_fields — deterministic completion of inline table-test
structs (the taskapipro blocker: a row uses a field the anonymous []struct
declaration lacks)."""
from src.builder import _fix_unknown_struct_fields, _infer_field_type


CODE = """package store

import "testing"

func TestMem(t *testing.T) {
	cases := []struct {
		name   string
		create models.Task
	}{
		{
			name:      "dup",
			create:    models.Task{ID: "1"},
			createErr: store.ErrExists,
		},
	}
	_ = cases
}
"""


def test_adds_missing_error_field():
    err = "internal/store/memory_test.go:13:4: unknown field createErr in struct literal of type struct{name string; create models.Task}"
    written = {"internal/store/memory_test.go": CODE}
    out = _fix_unknown_struct_fields(written, err)
    fixed = out["internal/store/memory_test.go"]
    decl = fixed[: fixed.index("}{")]
    assert "createErr error" in decl
    assert fixed.count("createErr") == 2  # decl + row


def test_named_type_not_touched():
    err = "internal/store/memory_test.go:12:4: unknown field createErr in struct literal of type models.Task"
    assert _fix_unknown_struct_fields({"internal/store/memory_test.go": CODE}, err) == {}


def test_uninferable_type_left_for_model():
    code = CODE.replace("createErr: store.ErrExists,", "createErr: someLocalVar,")
    err = "internal/store/memory_test.go:13:4: unknown field createErr in struct literal of type struct{name string}"
    assert _fix_unknown_struct_fields({"internal/store/memory_test.go": code}, err) == {}


def test_infer_types():
    assert _infer_field_type('"x"') == "string"
    assert _infer_field_type("true,") == "bool"
    assert _infer_field_type("42") == "int"
    assert _infer_field_type("store.ErrExists,") == "error"
    assert _infer_field_type("nil,") == "error"
    assert _infer_field_type("[]models.Task{{ID: \"1\"}},") == "[]models.Task"
    assert _infer_field_type("models.Task{ID: \"1\"},") == "models.Task"
    assert _infer_field_type("someLocalVar") is None
