from src.builder import (
    _fix_interface_missing_method,
    _lift_method_signature,
    _run_deterministic_gates,
)

# `x.Update undefined (type Store has no field or method Update)` — the model
# wrote Update on the concrete impl but forgot to declare it on the interface.
NOMETHOD = "type Store has no field or method Update"


def _store_iface(methods: str) -> str:
    return f"package main\n\ntype Store interface {{\n{methods}}}\n"


def _memstore(methods: str) -> str:
    return f"package main\n\ntype MemStore struct{{}}\n\n{methods}"


def test_fires_when_impl_has_method_interface_lacks_it():
    written = {
        "store.go": _store_iface("\tGet(id string) (Task, error)\n\tDelete(id string) error\n"),
        "memory.go": _memstore(
            "func (m *MemStore) Get(id string) (Task, error) { return Task{}, nil }\n"
            "func (m *MemStore) Delete(id string) error { return nil }\n"
            "func (m *MemStore) Update(t Task) error { return nil }\n"
        ),
    }
    err = f"./handlers.go:10:11: s.Update undefined ({NOMETHOD})"
    out = _fix_interface_missing_method(written, err)
    assert "store.go" in out
    # The interface gained exactly the impl's signature; the impl is untouched.
    assert "Update(t Task) error" in out["store.go"]
    assert out["store.go"].count("interface {") == 1
    assert "memory.go" not in out


def test_signature_fidelity_context_and_multi_return():
    written = {
        "store.go": _store_iface("\tGet(ctx context.Context, id string) (Task, error)\n"),
        "memory.go": _memstore(
            "func (m *MemStore) Get(ctx context.Context, id string) (Task, error) { return Task{}, nil }\n"
            "func (m *MemStore) Update(ctx context.Context, t Task) (Task, error) { return Task{}, nil }\n"
        ),
    }
    err = f"./h.go:1:1: s.Update undefined ({NOMETHOD})"
    out = _fix_interface_missing_method(written, err)
    assert "Update(ctx context.Context, t Task) (Task, error)" in out["store.go"]


def test_noop_case_b_missing_from_both_sides():
    # tasks-api-min: the model dropped Update from BOTH the interface and the impl,
    # so there is no signature to lift. The gate must leave it to the model.
    written = {
        "store.go": _store_iface("\tGet(id string) (Task, error)\n\tDelete(id string) error\n"),
        "memory.go": _memstore(
            "func (m *MemStore) Get(id string) (Task, error) { return Task{}, nil }\n"
            "func (m *MemStore) Delete(id string) error { return nil }\n"
        ),
    }
    err = f"./h.go:1:1: s.Update undefined ({NOMETHOD})"
    assert _fix_interface_missing_method(written, err) == {}


def test_noop_when_type_is_a_struct_not_an_interface():
    # A struct-missing-method is a different bug; the interface gate must ignore it.
    written = {
        "store.go": "package main\n\ntype Store struct{ n int }\n",
        "memory.go": _memstore("func (m *MemStore) Update(t Task) error { return nil }\n"),
    }
    err = f"./h.go:1:1: s.Update undefined ({NOMETHOD})"
    assert _fix_interface_missing_method(written, err) == {}


def test_noop_when_method_already_declared():
    written = {
        "store.go": _store_iface("\tGet(id string) (Task, error)\n\tUpdate(t Task) error\n"),
        "memory.go": _memstore(
            "func (m *MemStore) Get(id string) (Task, error) { return Task{}, nil }\n"
            "func (m *MemStore) Update(t Task) error { return nil }\n"
        ),
    }
    err = f"./h.go:1:1: s.Update undefined ({NOMETHOD})"
    assert _fix_interface_missing_method(written, err) == {}


def test_noop_cross_package_interface_and_impl_in_different_dirs():
    # Same-package guard: lifting a signature across packages risks type-name drift,
    # so the gate declines when the impl lives in another directory.
    written = {
        "internal/store/store.go": _store_iface("\tGet(id string) (Task, error)\n"),
        "internal/mem/mem.go": (
            "package mem\n\ntype MemStore struct{}\n\n"
            "func (m *MemStore) Get(id string) (Task, error) { return Task{}, nil }\n"
            "func (m *MemStore) Update(t Task) error { return nil }\n"
        ),
    }
    err = f"./h.go:1:1: s.Update undefined ({NOMETHOD})"
    assert _fix_interface_missing_method(written, err) == {}


def test_noop_when_no_type_implements_interface_plus_method():
    # A type with Update that does NOT implement the current interface is not the
    # real impl; the gate must not lift Update from it.
    written = {
        "store.go": _store_iface("\tGet(id string) (Task, error)\n\tDelete(id string) error\n"),
        "memory.go": _memstore(
            "func (m *MemStore) Get(id string) (Task, error) { return Task{}, nil }\n"
            "func (m *MemStore) Delete(id string) error { return nil }\n"
        ),
        "other.go": (
            "package main\n\ntype Other struct{}\n\n"
            "func (o *Other) Update(t Task) error { return nil }\n"
        ),
    }
    err = f"./h.go:1:1: s.Update undefined ({NOMETHOD})"
    # MemStore lacks Update; Other lacks Get/Delete -> no valid candidate.
    assert _fix_interface_missing_method(written, err) == {}


def test_noop_when_candidate_signatures_disagree():
    written = {
        "store.go": _store_iface("\tGet(id string) (Task, error)\n"),
        "a.go": (
            "package main\n\ntype A struct{}\n\n"
            "func (a *A) Get(id string) (Task, error) { return Task{}, nil }\n"
            "func (a *A) Update(t Task) error { return nil }\n"
        ),
        "b.go": (
            "package main\n\ntype B struct{}\n\n"
            "func (b *B) Get(id string) (Task, error) { return Task{}, nil }\n"
            "func (b *B) Update(id string, t Task) error { return nil }\n"  # different sig
        ),
    }
    err = f"./h.go:1:1: s.Update undefined ({NOMETHOD})"
    assert _fix_interface_missing_method(written, err) == {}


def test_noop_no_error():
    assert _fix_interface_missing_method({"a.go": "package a\n"}, "") == {}


def test_interface_and_impl_in_same_file():
    # tasks-api layout: Store interface and MemStore impl share store.go.
    written = {
        "store.go": (
            "package main\n\n"
            "type Store interface {\n\tGet(id int) (Task, error)\n}\n\n"
            "type MemStore struct{}\n\n"
            "func (m *MemStore) Get(id int) (Task, error) { return Task{}, nil }\n"
            "func (m *MemStore) Update(t Task) error { return nil }\n"
        ),
    }
    err = f"./h.go:1:1: s.Update undefined ({NOMETHOD})"
    out = _fix_interface_missing_method(written, err)
    assert "Update(t Task) error" in out["store.go"]


def test_two_methods_missing_from_same_interface_both_added():
    written = {
        "store.go": _store_iface("\tGet(id string) (Task, error)\n"),
        "memory.go": _memstore(
            "func (m *MemStore) Get(id string) (Task, error) { return Task{}, nil }\n"
            "func (m *MemStore) Update(t Task) error { return nil }\n"
            "func (m *MemStore) Delete(id string) error { return nil }\n"
        ),
    }
    err = (
        f"./h.go:1:1: s.Update undefined ({NOMETHOD})\n"
        "./h.go:2:1: s.Delete undefined (type Store has no field or method Delete)"
    )
    body = _fix_interface_missing_method(written, err)["store.go"]
    assert "Update(t Task) error" in body
    assert "Delete(id string) error" in body


def test_composes_in_deterministic_gate_chain():
    written = {
        "store.go": _store_iface("\tGet(id string) (Task, error)\n"),
        "memory.go": _memstore(
            "func (m *MemStore) Get(id string) (Task, error) { return Task{}, nil }\n"
            "func (m *MemStore) Update(t Task) error { return nil }\n"
        ),
    }
    err = f"./h.go:1:1: s.Update undefined ({NOMETHOD})"
    out = _run_deterministic_gates(written, err, None)
    assert "Update(t Task) error" in out["store.go"]


def test_lift_helper_bails_on_exotic_return():
    code = (
        "package main\n"
        "func (m *M) Weird(x int) struct{ A int } { return struct{ A int }{} }\n"
    )
    # A struct-typed return can't be transcribed onto one interface line safely.
    assert _lift_method_signature(code, "M", "Weird") is None


def test_lift_helper_value_and_unnamed_receivers():
    assert _lift_method_signature(
        "func (m M) Do(x int) error { return nil }\n", "M", "Do"
    ) == "Do(x int) error"
    assert _lift_method_signature(
        "func (*M) Do() { }\n", "M", "Do"
    ) == "Do()"
