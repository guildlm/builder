"""A two-value call used where one value is expected.

    return paginate(s.store.ListProjects(ctx), limit, offset), nil
    // multiple-value s.store.ListProjects(ctx) (value of type
    // ([]models.Project, error)) in single-value context

The store returns (items, error) and the model used the call as an argument,
dropping the error on the floor. Go cannot express that, so it does not compile.

This class stayed un-gated for months for a real reason: unlike every other gate
it must INTRODUCE statements rather than rewrite one. The enclosing function's
signature is what makes it tractable — the error goes to the last result, each
earlier result takes its zero value — so the repair is read off the AST rather
than guessed, and refused whenever the signature does not settle it.
"""

import shutil

import pytest

from src.builder import _fix_multivalue_in_single_context, _run_deterministic_gates

pytestmark = pytest.mark.skipif(
    shutil.which("go") is None, reason="needs the Go toolchain"
)

SRC = """package service

import "context"

type Project struct{ ID string }

type Store interface {
	ListProjects(ctx context.Context) ([]Project, error)
}

type svc struct{ store Store }

func paginate(items []Project, limit, offset int) []Project { return items }

func (s *svc) List(ctx context.Context, limit, offset int) ([]Project, error) {
	return paginate(s.store.ListProjects(ctx), limit, offset), nil
}
"""


def _err_at(src: str, needle: str, path: str = "service.go", typ: str = "[]Project") -> str:
    line = next(i for i, l in enumerate(src.splitlines(), 1) if needle in l)
    col = src.splitlines()[line - 1].index(needle) + 1
    return (
        f"./{path}:{line}:{col}: multiple-value {needle} "
        f"(value of type ({typ}, error)) in single-value context"
    )


ERR = _err_at(SRC, "s.store.ListProjects(ctx)")


def test_hoists_the_call_and_propagates_the_error():
    body = _fix_multivalue_in_single_context({"service.go": SRC}, ERR)["service.go"]
    assert "items, err := s.store.ListProjects(ctx)" in body
    assert "if err != nil {" in body
    assert "return nil, err" in body                       # slice zero value
    assert "return paginate(items, limit, offset), nil" in body
    assert "paginate(s.store.ListProjects(ctx)" not in body


def test_zero_value_for_a_provable_struct_is_a_composite_literal():
    # Project IS declared a struct in this file, so Project{} is provably its zero
    # value — not a guess.
    src = SRC.replace(
        "func (s *svc) List(ctx context.Context, limit, offset int) ([]Project, error) {\n"
        "\treturn paginate(s.store.ListProjects(ctx), limit, offset), nil\n}",
        "func (s *svc) First(ctx context.Context) (Project, error) {\n"
        "\treturn head(s.store.ListProjects(ctx)), nil\n}\n\n"
        "func head(p []Project) Project { return p[0] }",
    )
    err = _err_at(src, "s.store.ListProjects(ctx)")
    body = _fix_multivalue_in_single_context({"service.go": src}, err)["service.go"]
    assert "return Project{}, err" in body


CROSS_PKG = """package service

import (
	"context"

	"x/models"
)

type Store interface {
	ListProjects(ctx context.Context) ([]models.Project, error)
}

type svc struct{ store Store }

func head(p []models.Project) models.Project { return p[0] }

func (s *svc) First(ctx context.Context) (models.Project, error) {
	return head(s.store.ListProjects(ctx)), nil
}
"""


def test_refuses_a_zero_value_it_cannot_prove():
    # `models.Project{}` looks obvious and is not: if models.Project were an
    # interface, that literal would not compile — and this file cannot see the
    # other package to know. Refuse rather than guess.
    err = _err_at(CROSS_PKG, "s.store.ListProjects(ctx)")
    assert _fix_multivalue_in_single_context({"service.go": CROSS_PKG}, err) == {}


def test_refuses_when_the_function_does_not_return_an_error():
    # There is nowhere for the error to go.
    src = SRC.replace(
        "func (s *svc) List(ctx context.Context, limit, offset int) ([]Project, error) {\n"
        "\treturn paginate(s.store.ListProjects(ctx), limit, offset), nil\n}",
        "func (s *svc) List(ctx context.Context, limit, offset int) []Project {\n"
        "\treturn paginate(s.store.ListProjects(ctx), limit, offset)\n}",
    )
    err = _err_at(src, "s.store.ListProjects(ctx)")
    assert _fix_multivalue_in_single_context({"service.go": src}, err) == {}


def test_noop_without_the_error():
    assert _fix_multivalue_in_single_context({"service.go": SRC}, "") == {}


def test_composes_in_the_deterministic_gate_chain():
    out = _run_deterministic_gates({"service.go": SRC}, ERR, None)
    assert "items, err := s.store.ListProjects(ctx)" in out["service.go"]


TEST_FN = """package shortener

import (
	"errors"
	"testing"
)

func TestCodec(t *testing.T) {
	if !errors.Is(Decode("!"), ErrBadCode) {
		t.Errorf("Decode('!') = %v, want ErrBadCode", Decode("!"))
	}
	if !errors.Is(Decode(""), ErrBadCode) {
		t.Errorf("Decode('') = %v, want ErrBadCode", Decode(""))
	}
}
"""


def test_in_a_test_the_error_is_caught_not_propagated():
    """A TEST returns nothing, so there is nowhere to propagate an error to — and
    the gate refused, and shortener failed a sweep on it.

    But `errors.Is(X, target)` tells us, with certainty, that X must be the ERROR
    of the two returns. That is the one shape where the choice is not a guess."""
    err = _err_at(TEST_FN, 'Decode("!")', "shortener_test.go", "uint64")
    body = _fix_multivalue_in_single_context({"shortener_test.go": TEST_FN}, err)[
        "shortener_test.go"
    ]
    assert '_, err := Decode("!")' in body
    assert "errors.Is(err, ErrBadCode)" in body
    # The SAME call inside the if-body is repaired too, not left behind: the only
    # `Decode("!")` still in the file is the hoisted one.
    assert body.count('Decode("!")') == 1
    assert 't.Errorf("Decode(\'!\') = %v, want ErrBadCode", err)' in body


def test_it_refuses_when_the_wanted_value_is_a_guess():
    """`if Decode("x") != 5` wants the VALUE, not the error. Nothing says which of
    the two returns the caller meant, so the gate stays out."""
    src = TEST_FN.replace(
        '\tif !errors.Is(Decode("!"), ErrBadCode) {\n'
        '\t\tt.Errorf("Decode(\'!\') = %v, want ErrBadCode", Decode("!"))\n'
        '\t}\n',
        '\tif Decode("x") != 5 {\n\t\tt.Errorf("boom")\n\t}\n',
    )
    err = _err_at(src, 'Decode("x")', "shortener_test.go", "uint64")
    assert _fix_multivalue_in_single_context({"shortener_test.go": src}, err) == {}
