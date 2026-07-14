from src.builder import _widen_missing_symbol_targets

SERVICE = (
    "package service\n\n"
    "type Ledger struct {\n"
    "\tstore store.Store\n"
    "}\n\n"
    "func (l *Ledger) Post(t models.Transaction) error { return nil }\n"
)
API = (
    "package api\n\n"
    "type TransactionHandler struct{ l *service.Ledger }\n\n"
    "func (th *TransactionHandler) List(w http.ResponseWriter, r *http.Request) {\n"
    "\ttransactions := th.l.ListTransactions()\n"
    "}\n"
)
WRITTEN = {
    "internal/service/service.go": SERVICE,
    "internal/api/transactions.go": API,
}

# Verbatim from the held-out ledger run. The old regex — `type (\w+) has no field or
# method (\w+)` — could not match a pointer or a package qualifier, so the widener
# stayed silent and the loop regenerated the caller for three rounds.
ERR_POINTER_QUALIFIED = (
    "internal/api/transactions.go:37:23: th.l.ListTransactions undefined "
    "(type *service.Ledger has no field or method ListTransactions)"
)


def test_pointer_qualified_receiver_routes_to_the_declaring_file():
    out = _widen_missing_symbol_targets(
        ["internal/api/transactions.go"], WRITTEN, ERR_POINTER_QUALIFIED
    )
    assert "internal/service/service.go" in out
    assert "internal/api/transactions.go" in out  # the caller stays, we only ADD


def test_qualified_without_pointer_also_routes():
    err = (
        "internal/api/transactions.go:37:23: th.l.ListTransactions undefined "
        "(type service.Ledger has no field or method ListTransactions)"
    )
    out = _widen_missing_symbol_targets(["internal/api/transactions.go"], WRITTEN, err)
    assert "internal/service/service.go" in out


def test_bare_same_package_receiver_still_routes():
    # the form the widener already handled — it must keep working
    err = "a.go:9:5: s.Update undefined (type Store has no field or method Update)"
    written = {"store.go": "package main\n\ntype Store interface{}\n", "a.go": "package main\n"}
    out = _widen_missing_symbol_targets(["a.go"], written, err)
    assert "store.go" in out


def test_stdlib_receiver_widens_nothing():
    # `r.PathParam undefined (type *http.Request ...)` — a hallucinated stdlib method.
    # No project file declares `type Request`, so there is nothing to widen to, and
    # the model must fix the CALL. The looser regex must not invent a target here.
    err = (
        "internal/api/accounts.go:43:10: r.PathParam undefined "
        "(type *http.Request has no field or method PathParam)"
    )
    out = _widen_missing_symbol_targets(["internal/api/accounts.go"], WRITTEN, err)
    assert out == ["internal/api/accounts.go"]


def test_shadowed_tester_is_not_widened():
    # `t.Fatalf undefined (type Task has no field or method Fatalf)` reads the same and
    # is a different bug entirely — a loop variable named t stole the *testing.T.
    # Widening would invite the model to give Task a Fatalf method. _fix_shadowed_tester
    # owns it; the widener must stay out.
    err = "models_test.go:12:4: t.Fatalf undefined (type Task has no field or method Fatalf)"
    written = {"models.go": "package main\n\ntype Task struct{}\n", "models_test.go": "package main\n"}
    out = _widen_missing_symbol_targets(["models_test.go"], written, err)
    assert "models.go" not in out
