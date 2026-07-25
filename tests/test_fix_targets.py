"""_fix_targets: what a fix round REPAIRS vs what the toolchain BLAMED.

The fix loop asks two different questions of the same error output. Repair wants breadth
(the file the error names may be the correct one); escalation wants precision (handing a
file to a bigger fleet member costs that model on every later round and is not monotone).
_fix_targets answers both, and these tests pin the split — pure, so no Go toolchain is
needed; the end-to-end consequence is covered by
test_builder.py::test_escalation_counts_only_the_blamed_file_not_the_widened_package.
"""

from __future__ import annotations

from src.builder import FileSpec, _fix_targets

IMPL = "package store\n\nfunc Add(a, b int) int { return a + b }\n"
TEST = "package store\n\nimport \"testing\"\n\nfunc TestAdd(t *testing.T) {}\n"


def test_blamed_is_only_what_the_error_names_while_targets_widen():
    """A persistent runtime failure widens to the package impl so the model can fix
    whichever side is wrong — but the impl was never blamed, so it must not appear in
    `blamed` (it would earn an escalation strike it did not deserve)."""
    written = {"store.go": IMPL, "store_test.go": TEST}
    output = "--- FAIL: TestAdd (0.00s)\n    store_test.go:4: got 3 want 4\nFAIL\n"
    # dir already failed once at runtime -> this round widens
    targets, blamed = _fix_targets(written, output, {"": 1}, [])

    assert blamed == ["store_test.go"]
    assert set(targets) == {"store_test.go", "store.go"}, "the impl should be widened in"


def test_first_runtime_round_does_not_widen_yet():
    """The cheap common case comes first: give the test author one round alone."""
    written = {"store.go": IMPL, "store_test.go": TEST}
    output = "--- FAIL: TestAdd (0.00s)\n    store_test.go:4: got 3 want 4\nFAIL\n"
    targets, blamed = _fix_targets(written, output, {}, [])

    assert targets == ["store_test.go"]
    assert blamed == ["store_test.go"]


def test_unattributed_error_blames_nothing_and_repairs_everything():
    """When the error names no file we know, the loop still has to try something, so it
    repairs every file — but there is no basis for choosing one to escalate, so `blamed`
    is empty and no file earns a strike."""
    written = {"store.go": IMPL, "store_test.go": TEST}
    targets, blamed = _fix_targets(written, "go: some toolchain complaint\n", {}, [])

    assert blamed == []
    assert set(targets) == {"store.go", "store_test.go"}


def test_promised_symbol_widens_the_owner_without_blaming_it():
    """`undefined: NewStore` is reported at the USE site; the spec says store.go was
    supposed to declare it, so store.go joins the repair — on a hypothesis, so it stays
    out of `blamed`."""
    written = {"store.go": IMPL, "store_test.go": TEST}
    output = "./store_test.go:6:9: undefined: NewStore\n"
    specs = [
        FileSpec(path="store.go", purpose="declares the constructor NewStore"),
        FileSpec(path="store_test.go", purpose="tests the store"),
    ]
    targets, blamed = _fix_targets(written, output, {}, specs)

    assert blamed == ["store_test.go"]
    assert set(targets) == {"store_test.go", "store.go"}


def test_blamed_preserves_the_deterministic_file_order():
    """Fix order is part of the build's determinism (the routing A/B relies on two arms
    being byte-identical until they diverge), so blame must not be order-scrambled."""
    written = {"a.go": IMPL, "b.go": IMPL, "c.go": IMPL}
    output = "./c.go:1:1: boom\n./a.go:2:2: boom\n"
    targets, blamed = _fix_targets(written, output, {}, [])

    assert blamed == ["a.go", "c.go"], "order follows `written`, not the error text"
    assert targets == blamed
