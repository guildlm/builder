from src.builder import _fix_pointer_to_interface, _run_deterministic_gates

# `h.store.CreateTask undefined (type *Store is pointer to interface, not interface)`
PTRIFACE = "type *Store is pointer to interface, not interface"

IFACE = "package main\n\ntype Store interface {\n\tCreateTask(t Task) error\n}\n"


def test_fires_on_field_and_param():
    written = {
        "store.go": IFACE,
        "handler.go": (
            "package main\n\n"
            "type H struct {\n\tstore *Store\n}\n\n"
            "func NewH(store *Store) *H { return &H{store: store} }\n\n"
            "func (h *H) do(t Task) error { return h.store.CreateTask(t) }\n"
        ),
    }
    err = f"./handler.go:9:20: h.store.CreateTask undefined ({PTRIFACE})"
    out = _fix_pointer_to_interface(written, err)
    body = out["handler.go"]
    assert "store *Store" not in body
    assert "store Store" in body          # field fixed
    assert "func NewH(store Store)" in body  # param fixed
    assert "*H" in body                    # pointer-to-STRUCT receiver untouched
    assert "store.go" not in out           # interface decl file unchanged


def test_noop_when_type_is_a_struct_not_interface():
    # A pointer to a STRUCT is valid Go and must never be rewritten.
    written = {
        "store.go": "package main\n\ntype Store struct{ n int }\n",
        "handler.go": (
            "package main\n\ntype H struct{ store *Store }\n"
            "func (h *H) n() int { return h.store.n }\n"
        ),
    }
    err = f"./handler.go:1:1: whatever ({PTRIFACE})"
    # Even though the (fabricated) error text mentions it, Store is a struct here,
    # so the interface guard must refuse to touch *Store.
    assert _fix_pointer_to_interface(written, err) == {}


def test_collapses_multiple_stars():
    written = {
        "store.go": IFACE,
        "h.go": "package main\n\nfunc f(x **Store) {}\n",
    }
    err = f"./h.go:1:1: x undefined ({PTRIFACE})"
    assert "f(x Store)" in _fix_pointer_to_interface(written, err)["h.go"]


def test_fixes_slice_and_map_element_types():
    written = {
        "store.go": IFACE,
        "h.go": (
            "package main\n\n"
            "type Reg struct {\n\tall []*Store\n\tby  map[string]*Store\n}\n"
        ),
    }
    err = f"./h.go:1:1: undefined ({PTRIFACE})"
    body = _fix_pointer_to_interface(written, err)["h.go"]
    assert "all []Store" in body
    assert "by  map[string]Store" in body


def test_does_not_touch_concrete_pointer_in_assertion():
    # `var _ Store = (*MemStore)(nil)` must survive: *MemStore is a concrete
    # pointer implementing the interface, not a pointer-to-interface.
    written = {
        "store.go": IFACE + "\ntype MemStore struct{}\nvar _ Store = (*MemStore)(nil)\n",
        "handler.go": (
            "package main\n\ntype H struct{ store *Store }\n"
            "func (h *H) do(t Task) error { return h.store.CreateTask(t) }\n"
        ),
    }
    err = f"./handler.go:1:1: h.store.CreateTask undefined ({PTRIFACE})"
    out = _fix_pointer_to_interface(written, err)
    assert "(*MemStore)(nil)" in out["store.go"] if "store.go" in out else True
    assert "store Store" in out["handler.go"]  # the pointer-to-interface is fixed


def test_noop_no_error():
    assert _fix_pointer_to_interface({"a.go": "package a\n"}, "") == {}


def test_composes_in_deterministic_gate_chain():
    written = {
        "store.go": IFACE,
        "handler.go": (
            "package main\n\ntype H struct{ store *Store }\n"
            "func (h *H) do(t Task) error { return h.store.CreateTask(t) }\n"
        ),
    }
    err = f"./handler.go:1:1: h.store.CreateTask undefined ({PTRIFACE})"
    out = _run_deterministic_gates(written, err, None)
    assert "store Store" in out["handler.go"]
