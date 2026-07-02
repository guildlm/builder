"""Tests for the deterministic assignment-arity gate (_fix_assignment_arity)."""

from src.builder import _fix_assignment_arity


ERR = (
    "internal/store/memory_test.go:12:9: assignment mismatch: "
    "2 variables but s.Delete returns 1 value"
)


def _file(line: str, lineno: int = 12) -> str:
    lines = ["package store"] + [""] * (lineno - 2)
    lines.insert(lineno - 1, line)
    return "\n".join(lines) + "\n"


def test_drops_trailing_blank():
    code = _file("\tgot, _ := s.Delete(id)")
    changed = _fix_assignment_arity({"internal/store/memory_test.go": code}, ERR)
    assert "\tgot := s.Delete(id)" in changed["internal/store/memory_test.go"]


def test_drops_rightmost_blank_first():
    code = _file("\t_, got, _ := s.Delete(id)")
    err = ERR.replace("2 variables", "3 variables").replace(
        "1 value", "2 values"
    )
    changed = _fix_assignment_arity({"internal/store/memory_test.go": code}, err)
    assert "\t_, got := s.Delete(id)" in changed["internal/store/memory_test.go"]


def test_pads_with_blanks_when_too_few():
    code = _file("\ttask := svc.Create(ctx, in)")
    err = (
        "internal/service/service_test.go:12:9: assignment mismatch: "
        "1 variable but svc.Create returns 2 values"
    )
    changed = _fix_assignment_arity(
        {"internal/service/service_test.go": code}, err
    )
    assert "\ttask, _ := svc.Create(ctx, in)" in changed[
        "internal/service/service_test.go"
    ]


def test_named_extra_var_is_left_alone():
    # dropping a NAMED variable could hide a real bug — model's job
    code = _file("\tgot, err := s.Delete(id)")
    changed = _fix_assignment_arity({"internal/store/memory_test.go": code}, ERR)
    assert changed == {}


def test_plain_assignment_and_all_blank_lhs():
    code = _file("\tgot, _ = s.Delete(id)")
    changed = _fix_assignment_arity({"internal/store/memory_test.go": code}, ERR)
    assert "\tgot = s.Delete(id)" in changed["internal/store/memory_test.go"]
    # all-blank := after the drop must degrade to = (":=" declares nothing)
    code2 = _file("\t_, _ := s.Delete(id)")
    err2 = ERR.replace("2 variables", "2 variables")
    changed2 = _fix_assignment_arity({"internal/store/memory_test.go": code2}, err2)
    assert "\t_ = s.Delete(id)" in changed2["internal/store/memory_test.go"]


def test_returns_zero_values_is_skipped():
    code = _file("\tgot := s.Close()")
    err = (
        "internal/store/memory_test.go:12:9: assignment mismatch: "
        "1 variable but s.Close returns 0 values"
    )
    changed = _fix_assignment_arity({"internal/store/memory_test.go": code}, err)
    assert changed == {}


def test_comparison_line_is_not_mangled():
    # an `==` on the reported line must not be treated as an assignment
    code = _file("\tif got == want {")
    changed = _fix_assignment_arity({"internal/store/memory_test.go": code}, ERR)
    assert changed == {}
