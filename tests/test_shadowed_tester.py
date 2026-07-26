"""The shadowed-tester gate: `for _, t := range tasks` steals the *testing.T
parameter, so `t.Fatalf` inside the body resolves to a Task.

These tests exercise the go/ast rewriter through the Python gate, so they need a
Go toolchain — the same hard dependency the rest of the build loop already has.
"""

import shutil

import pytest

from src.builder import (
    _fix_shadowed_tester,
    _run_deterministic_gates,
    _widen_missing_symbol_targets,
)

pytestmark = pytest.mark.skipif(
    shutil.which("go") is None, reason="needs the Go toolchain"
)

ERR = (
    "./store_test.go:33:6: t.Fatalf undefined "
    "(type Task has no field or method Fatalf)"
)

MODEL = "package main\n\ntype Task struct {\n\tID    int\n\tTitle string\n}\n"

SHADOWED = """package main

import "testing"

func TestStoreListSorted(t *testing.T) {
	s := NewStore()
	tasks := []Task{{Title: "b"}, {Title: "a"}}
	for _, t := range tasks {
		if err := s.Create(t); err != nil {
			t.Fatalf("Create: %v", err)
		}
	}
	if len(s.List()) != 2 {
		t.Errorf("List: want 2")
	}
}
"""


def test_renames_the_shadow_and_restores_the_tester():
    out = _fix_shadowed_tester({"model.go": MODEL, "store_test.go": SHADOWED}, ERR)
    body = out["store_test.go"]
    assert "for _, tk := range tasks" in body   # the shadow is renamed
    assert "s.Create(tk)" in body               # a bare use IS the domain value
    assert "t.Fatalf(" in body                  # the tester call is left alone
    assert "tk.Fatalf" not in body              # ...and never renamed
    assert "func TestStoreListSorted(t *testing.T)" in body  # param untouched
    assert "t.Errorf(" in body                  # uses outside the scope untouched


def test_output_compiles_as_go():
    # The rewrite goes through go/format, so the result must still parse.
    body = _fix_shadowed_tester({"model.go": MODEL, "store_test.go": SHADOWED}, ERR)[
        "store_test.go"
    ]
    assert body.startswith("package main")
    assert body.count("{") == body.count("}")


def test_noop_without_the_error():
    assert _fix_shadowed_tester({"store_test.go": SHADOWED}, "") == {}


def test_noop_on_a_plain_missing_method_error():
    # `type Store has no field or method Update` is the interface gate's class,
    # not ours: the receiver is not `t`.
    err = "./h.go:9:2: s.Update undefined (type Store has no field or method Update)"
    assert _fix_shadowed_tester({"store_test.go": SHADOWED}, err) == {}


def test_noop_when_the_domain_type_has_a_testing_shaped_method():
    # If Task itself declares Error(), then `t.Error(...)` inside the shadow is
    # genuinely ambiguous — the gate must refuse to guess.
    model = MODEL + "\nfunc (t Task) Error() string { return t.Title }\n"
    assert _fix_shadowed_tester({"model.go": model, "store_test.go": SHADOWED}, ERR) == {}


def test_noop_when_the_domain_type_has_a_testing_shaped_field():
    # `Task.Name` is an utterly ordinary field, and Name is also a *testing.T
    # method — so `t.Name` inside the shadow reads both ways. Refuse.
    model = "package main\n\ntype Task struct {\n\tID   int\n\tName string\n}\n"
    assert _fix_shadowed_tester({"model.go": model, "store_test.go": SHADOWED}, ERR) == {}


def test_noop_on_non_test_files():
    # The error names a _test.go file; a same-named symbol elsewhere is not ours.
    assert _fix_shadowed_tester({"store.go": SHADOWED}, ERR) == {}


def test_noop_on_an_inner_reshadow():
    # Two nested bindings of `t` — a use in the inner body could belong to
    # either, so the gate bails rather than pick one.
    src = """package main

import "testing"

func TestNested(t *testing.T) {
	for _, t := range tasks {
		for _, t := range t.Subs {
			t.Fatalf("boom")
		}
	}
}
"""
    assert _fix_shadowed_tester({"model.go": MODEL, "store_test.go": src}, ERR) == {}


def test_noop_when_the_shadow_is_never_used_as_a_tester():
    # `for _, t := range` with no t.Fatalf inside compiles fine. Not our business.
    src = """package main

import "testing"

func TestFine(t *testing.T) {
	total := 0
	for _, t := range tasks {
		total += t.ID
	}
	if total == 0 {
		t.Fatalf("empty")
	}
}
"""
    assert _fix_shadowed_tester({"model.go": MODEL, "store_test.go": src}, ERR) == {}


def test_handles_a_short_variable_declaration_shadow():
    # Not just range loops: `t := tasks[0]` shadows for the rest of the block.
    src = """package main

import "testing"

func TestOne(t *testing.T) {
	t := tasks[0]
	if t.Title != "a" {
		t.Fatalf("want a, got %q", t.Title)
	}
}
"""
    body = _fix_shadowed_tester({"model.go": MODEL, "store_test.go": src}, ERR)[
        "store_test.go"
    ]
    assert "tk := tasks[0]" in body
    assert 'if tk.Title != "a"' in body
    assert "t.Fatalf(" in body
    assert "tk.Title)" in body  # the argument is the domain value, still renamed


def test_noop_on_a_declaration_in_an_if_init_clause():
    # `if t := ...;` scopes t to the if statement, NOT to the rest of the
    # enclosing block. The innermost enclosing block over-approximates that
    # span, so renaming across it would rewrite the real tester below (the bare
    # `check(t)` here). The gate must bail instead.
    src = """package main

import "testing"

func TestInit(t *testing.T) {
	if t := tasks[0]; t.ID == 0 {
		t.Fatalf("no id")
	}
	check(t)
}
"""
    assert _fix_shadowed_tester({"model.go": MODEL, "store_test.go": src}, ERR) == {}


def test_picks_a_name_that_is_not_already_taken():
    src = SHADOWED.replace("s := NewStore()", "s := NewStore()\n\ttk := 1\n\t_ = tk")
    body = _fix_shadowed_tester({"model.go": MODEL, "store_test.go": src}, ERR)[
        "store_test.go"
    ]
    assert "for _, tv := range tasks" in body  # tk was taken, so it moved on
    assert "s.Create(tv)" in body


def test_leaves_a_shadow_in_a_non_tester_function_alone():
    # No `t *testing.T` parameter -> naming a variable `t` is perfectly fine.
    src = """package main

func helper(tasks []Task) int {
	n := 0
	for _, t := range tasks {
		n += t.ID
	}
	return n
}
"""
    assert _fix_shadowed_tester({"model.go": MODEL, "store_test.go": src}, ERR) == {}


def test_never_renames_an_idiomatic_subtest_parameter():
    # `t.Run("x", func(t *testing.T) {...})` re-binds t to a NEW tester. That is
    # correct, idiomatic Go — not the bug. Renaming it would still compile while
    # silently reporting failures against the parent test, so the gate must leave
    # the subtest alone even while it repairs the real shadow in the same file.
    src = """package main

import "testing"

func TestBoth(t *testing.T) {
	t.Run("sub", func(t *testing.T) {
		if 1 != 1 {
			t.Fatalf("impossible")
		}
	})
	for _, t := range tasks {
		if err := s.Create(t); err != nil {
			t.Fatalf("Create: %v", err)
		}
	}
}
"""
    body = _fix_shadowed_tester({"model.go": MODEL, "store_test.go": src}, ERR)[
        "store_test.go"
    ]
    assert 'func(t *testing.T)' in body      # the subtest parameter is untouched
    assert "func(tk *testing.T)" not in body
    assert "for _, tk := range tasks" in body  # ...and the real shadow is fixed
    assert "s.Create(tk)" in body


def test_the_shadow_error_no_longer_drags_the_model_file_into_the_fix():
    # `t.Fatalf undefined (type Task has no field or method Fatalf)` reads exactly
    # like a genuinely missing method, and the root-cause widening used to believe
    # it: it added task.go to the fix targets and invited the model to give Task a
    # Fatalf method. It must now recognise the shadow and stay out.
    written = {"model.go": MODEL, "store_test.go": SHADOWED}
    assert _widen_missing_symbol_targets(["store_test.go"], written, ERR) == [
        "store_test.go"
    ]


def test_a_genuinely_missing_method_still_widens():
    # The widening must keep working for the error it was written for.
    written = {
        "store.go": "package main\n\ntype Store interface{ Get(id int) error }\n",
        "api.go": "package main\n",
    }
    err = "./api.go:9:2: s.Update undefined (type Store has no field or method Update)"
    assert "store.go" in _widen_missing_symbol_targets(["api.go"], written, err)


def test_composes_in_the_deterministic_gate_chain():
    out = _run_deterministic_gates(
        {"model.go": MODEL, "store_test.go": SHADOWED}, ERR, None
    )
    assert "for _, tk := range tasks" in out["store_test.go"]
    assert "t.Fatalf(" in out["store_test.go"]


REDECLARED_ERR = (
    "./x_test.go:6:6: t redeclared in this block\n"
    "\t./x_test.go:5:27: other declaration of t\n"
    "./x_test.go:7:4: t.Title undefined "
    "(type *testing.T has no field or method Title)"
)

VAR_T_SHADOW = """package main

import "testing"

func TestTaskNameNotEmpty(t *testing.T) {
	var t Task
	t.Title = "alpha"
	if t.Name() == "" {
		t.Fatalf("Name() must not be empty")
	}
}
"""


def test_refuses_the_redeclaration_form_when_the_domain_type_is_ambiguous():
    """The ambiguity guard was VACUOUS on two of the three shapes.

    It reads the type off the compiler message, and only `t.Fatalf undefined (type
    Task has no field or method Fatalf)` carries one. For `var t Task` Go names
    *testing.T instead — the parameter wins the block — so `hits` is empty and the
    loop over it guards nothing.

    Measured on the fixture below, before this test existed: the gate rewrote it to
    `var tk Task` / `tk.Title = "alpha"` while leaving `t.Name()` alone, because
    Name is a *testing.T method. That TYPE-CHECKS. The suite went from a compile
    error to GREEN with the assertion reading the TEST's own name — never empty, so
    the check can never fail again. A gate that manufactures a permanently vacuous
    test is worse than the compile error it removed.
    """
    model = MODEL + "\nfunc (x Task) Name() string { return x.Title }\n"
    assert _fix_shadowed_tester({"model.go": model, "x_test.go": VAR_T_SHADOW},
                                REDECLARED_ERR) == {}


def test_refuses_the_assignment_form_when_the_domain_type_is_ambiguous():
    # Same blind spot, the other shape: `t := models.Task{...}` reads as an
    # assignment to the tester, so the compiler names *testing.T here too.
    src = """package main

import "testing"

func TestCreateOK(t *testing.T) {
	t := models.Task{Title: "task1"}
	if t.Name() == "" {
		t.Fatalf("Name")
	}
}
"""
    model = MODEL + "\nfunc (x Task) Name() string { return x.Title }\n"
    err = (
        "./service_test.go:6:7: cannot use models.Task{…} (value of struct type "
        "models.Task) as *testing.T value in assignment"
    )
    assert _fix_shadowed_tester({"model.go": model, "service_test.go": src}, err) == {}


def test_the_source_guard_does_not_over_refuse_an_ordinary_domain_type():
    # The guard must cost nothing on the shape it was written around: tasks-api's
    # Task carries ID/Title/Done and nothing testing-shaped, so `var t Task` is
    # still repaired. Refusing here would restore the 3381-second compile deadlock
    # that the redeclaration trigger was added to break.
    src = """package main

import "testing"

func TestTitle(t *testing.T) {
	var t Task
	t.Title = "alpha"
	if t.Title != "alpha" {
		t.Fatalf("want alpha")
	}
}
"""
    body = _fix_shadowed_tester({"model.go": MODEL, "x_test.go": src},
                                REDECLARED_ERR)["x_test.go"]
    assert "var tk Task" in body
    assert 'tk.Title = "alpha"' in body
    assert 'if tk.Title != "alpha"' in body   # the domain use follows the rename
    assert "t.Fatalf(" in body                # ...and the tester is restored


def test_fires_when_go_reports_it_as_an_assignment_to_the_tester():
    """The SAME mistake, reported completely differently.

    `t := models.Task{...}` in a function whose parameter is already `t` does not
    shadow anything — a parameter lives in the body's own scope — so Go reads it
    as an ASSIGNMENT to the tester and complains about the type:

        cannot use models.Task{…} (value of struct type models.Task) as
        *testing.T value in assignment

    `t.Fatalf` still resolves to *testing.T, so the "has no field or method"
    message never appears, and the gate never fired — even though its rewriter
    repairs the file perfectly the moment it is handed it. workapi failed a sweep
    on this. One regex stood between a working gate and a red spec."""
    src = """package service

import "testing"

func TestCreateOK(t *testing.T) {
	svc := NewTaskService()
	t := models.Task{ID: "1", Title: "task1"}
	if _, err := svc.Create(t); err != nil {
		t.Fatalf("Create: %v", err)
	}
}
"""
    err = (
        "./service_test.go:7:7: cannot use models.Task{…} (value of struct type "
        "models.Task) as *testing.T value in assignment"
    )
    body = _fix_shadowed_tester({"model.go": MODEL, "service_test.go": src}, err)[
        "service_test.go"
    ]
    assert "tk := models.Task{" in body     # the value gets its own name
    assert "svc.Create(tk)" in body         # and the bare use follows it
    assert "t.Fatalf(" in body              # the tester is restored, untouched
