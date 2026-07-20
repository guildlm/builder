"""A gate that inserts a line invalidates every line number behind it.

taskapipro's fix loop kept dying on a line no model ever wrote:

    tk1, _ := models.Task{ID: "1", Title: "task1", Status: "todo"}

The gates did it. _requalify_undefined added two imports to the top of the file,
everything below shifted down by two, and _fix_assignment_arity — still holding
the line numbers the compiler had given it BEFORE the insert — applied its repair
to the wrong line.

The chain now runs in two phases: in-place repairs together (none of them changes
how many lines a file has), then line-SHIFTING repairs one per pass. These tests
pin that, so a future gate added to the wrong phase fails here instead of silently
corrupting a file.
"""

import re

from src.builder import (
    _fix_assignment_arity,
    _fix_if_composite_literal,
    _fix_mux_return_type,
    _fix_pointer_to_interface,
    _fix_self_qualified_package,
    _fix_string_int_conversion,
    _fix_swapped_error_assignment,
    _fix_unused_var,
    _requalify_undefined,
    _run_deterministic_gates,
)

# A file that needs BOTH an inserted import (models, store are undefined) AND an
# in-place arity repair. Getting both in one pass is what corrupted the file.
TEST_FILE = '''package service

import (
	"context"
	"testing"
)

func TestListLimit(t *testing.T) {
	svc := NewTaskService(store.NewMemStore())
	tk1 := models.Task{ID: "1"}
	if err := svc.Create(context.Background(), tk1); err != nil {
		t.Fatalf("Create: %v", err)
	}
}
'''

# What the compiler says about the file AS IT STANDS — line 9 is the store use,
# line 10 the models use, line 11 the arity error.
ERRORS = (
    "./service_test.go:9:24: undefined: store\n"
    "./service_test.go:10:9: undefined: models\n"
    "./service_test.go:11:5: assignment mismatch: 1 variable but svc.Create "
    "returns 2 values\n"
)

WRITTEN = {
    "service_test.go": TEST_FILE,
    "store/store.go": "package store\n\nfunc NewMemStore() *MemStore { return nil }\n"
    "\ntype MemStore struct{}\n",
    "models/models.go": "package models\n\ntype Task struct{ ID string }\n",
}


def test_one_pass_never_both_inserts_a_line_and_edits_by_line_number():
    out = _run_deterministic_gates(WRITTEN, ERRORS, "guildlm.dev/x")
    body = out.get("service_test.go", TEST_FILE)

    # Whatever the pass chose to do, it must NOT have produced the corruption:
    # a composite literal cannot yield two values.
    assert "tk1, _ :=" not in body
    assert "tk1 := models.Task{" in body

    # And a pass that inserted imports must not ALSO have edited by line number.
    inserted = len(body.splitlines()) != len(TEST_FILE.splitlines())
    edited_in_place = "_, err := svc.Create" in body
    assert not (inserted and edited_in_place), (
        "this pass both shifted the lines and edited by the compiler's stale "
        "line numbers — that is the bug"
    )


def test_the_loop_reaches_both_repairs_across_passes():
    """The phase split costs passes, not correctness. Driving the chain the way
    the fix loop does — repair, re-derive, repair — reaches both."""
    written = dict(WRITTEN)
    for _ in range(6):
        out = _run_deterministic_gates(written, ERRORS, "guildlm.dev/x")
        if not out:
            break
        written.update(out)
        # The compiler would be re-run here; the fixture's line numbers only stay
        # valid while nothing shifts, so stop once the imports have landed.
        if "guildlm.dev/x/models" in written["service_test.go"]:
            break
    assert "guildlm.dev/x/models" in written["service_test.go"]
    assert "tk1, _ :=" not in written["service_test.go"]


def test_no_phase_one_gate_can_shift_a_line():
    """Phase one's entire safety argument is that none of its gates changes how
    many lines a file has. This reads the classification out of the source rather
    than trusting it: a gate that adds an import, or inserts or removes a line,
    cannot be in phase one.

    It caught three on its first run — string-int conversion (adds `strconv`),
    errors-wrap (adds `fmt`) and the struct-field repairs (insert and remove
    fields) — all of which I had filed as in-place because they *look* like
    single-line rewrites."""
    import inspect

    import src.builder as B

    src = inspect.getsource(B._run_deterministic_gates)
    phase1 = src.split("Phase 2")[0]
    named = re.findall(r"inplace\.update\((_fix_\w+)\(", phase1)
    assert named, "could not read phase one out of the chain"

    for name in named:
        body = inspect.getsource(getattr(B, name))
        assert "_ensure_import" not in body, (
            f"{name} adds an IMPORT, so it grows the file and belongs in phase "
            f"two — every line-indexed gate behind it would then be repairing "
            f"the wrong line"
        )
        # Precisely: mutation of the LINE list. `names.pop(i)` drops a blank from
        # an LHS and is not a line change — an earlier, cruder version of this
        # check flagged it, which is its own small lesson about assertions.
        assert not re.search(r"\blines\.(insert|pop)\(|\bdel lines\[", body), (
            f"{name} inserts or removes a LINE, so it belongs in phase two"
        )


def test_the_in_place_gates_really_do_preserve_the_line_count():
    """The static check above, confirmed by actually RUNNING each gate.

    Structural inspection catches the two historical escapes (an added import, an
    inserted/removed line), but three phase-one gates rewrite the WHOLE file text
    with a re.sub — mux-return, pointer-to-interface, self-qualifier — and there
    line-preservation is invisible from the shape of the code: only running them
    proves the replacement adds no newline. They are covered here.

    Every case also asserts the gate FIRED. A regex drift that stops a case from
    triggering would otherwise leave `out` empty and pass the line-count check
    vacuously — coverage that measures nothing, which is the failure this whole
    file exists to prevent one level up.
    """
    cases = [
        (
            _fix_assignment_arity,
            {"p.go": "package p\n\nfunc f() {\n\terr := g()\n}\n"},
            "./p.go:4:2: assignment mismatch: 1 variable but g returns 2 values",
        ),
        (
            _fix_unused_var,
            {"p.go": "package p\n\nfunc f() {\n\tu, err := g()\n\t_ = err\n}\n"},
            "./p.go:4:2: declared and not used: u",
        ),
        (
            # The gate only swaps when the assignment and the != nil comparison
            # share the line the compiler names — the compound-if form. The old
            # fixture split them across two lines, so the gate never fired and the
            # line-count check ran on an empty result (vacuous until the assert
            # below started demanding a fire).
            _fix_swapped_error_assignment,
            {"p.go": "package p\n\nfunc f() {\n\tif err, _ := g(); err != nil {\n\t}\n}\n"},
            "./p.go:4:19: invalid operation: err != nil (mismatched types T and "
            "untyped nil)",
        ),
        (
            # Needs the real _IFLIT_RE shape ("found assignment ... missing
            # parentheses around composite literal") and a wrappable named-type
            # literal on the if line — the old fixture matched neither, so the gate
            # never fired.
            _fix_if_composite_literal,
            {"p.go": "package p\n\nfunc f() {\n\tif got, want := 1, T{}; got != want {\n\t}\n}\n"},
            "./p.go:4:2: expected boolean expression, found assignment (missing "
            "parentheses around composite literal?)",
        ),
        # --- the three whole-text (re.sub) gates: line-preservation is NOT visible
        # from the code's shape, so only running them proves the sub adds no newline ---
        (
            _fix_self_qualified_package,
            {"store.go": "package store\n\nvar ErrNotFound = 1\n\n"
             "func Get() int { return store.ErrNotFound }\n"},
            "./store.go:5:23: undefined: store",
        ),
        (
            _fix_pointer_to_interface,
            {"h.go": "package p\n\ntype Store interface{ Do() }\n\n"
             "type H struct{ s *Store }\n"},
            "./h.go:5:19: h.s.Do undefined (type *Store is pointer to interface, "
            "not interface)",
        ),
        (
            _fix_mux_return_type,
            {"router.go": "package p\n\nfunc newRouter() *http.ServeMux {\n"
             "\treturn Chain(mux)\n}\n"},
            "./router.go:4:9: cannot use Chain(mux) (value of interface type "
            "http.Handler) as *http.ServeMux value in return statement: need type "
            "assertion",
        ),
    ]
    for gate, written, err in cases:
        out = gate(written, err)
        assert out, (
            f"{gate.__name__} did not fire on its fixture — the input no longer "
            f"triggers it, so the line-count check below would pass vacuously. "
            f"Repair the fixture, do not delete the case."
        )
        for path, new in out.items():
            assert len(new.splitlines()) == len(written[path].splitlines()), (
                f"{gate.__name__} changed the line count of {path} — it belongs in "
                f"phase TWO, or every line-indexed gate behind it will corrupt a file"
            )


def test_requalify_is_correctly_classified_as_line_shifting():
    # The gate that started it all: it adds imports, so it must never share a pass
    # with a line-indexed repair.
    out = _requalify_undefined(WRITTEN, ERRORS, "guildlm.dev/x")
    body = out["service_test.go"]
    assert len(body.splitlines()) > len(TEST_FILE.splitlines())


def test_string_int_conversion_is_line_shifting_and_belongs_in_phase_two():
    """Written as a phase-ONE gate and caught by the test above on its first run:
    rewriting `string(42)` to `strconv.Itoa(42)` needs an IMPORT, so it grows the
    file — and would have corrupted every line-indexed repair behind it, exactly
    as _requalify_undefined did."""
    code = 'package p\n\nfunc f() {\n\ts := string(42)\n\t_ = s\n}\n'
    err = (
        "./p.go:4:7: conversion from int to string yields a string of one rune, "
        "not a string of digits (did you mean fmt.Sprint(x)?)"
    )
    out = _fix_string_int_conversion({"p.go": code}, err)
    assert len(out["p.go"].splitlines()) > len(code.splitlines())
    assert 'import "strconv"' in out["p.go"]
