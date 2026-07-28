"""`%)` is not a format verb — repair it, or refuse, but never guess.

Written from a live failure. shortener's spec shows `t.Fatalf("Decode(%q): %v", ...)` and a
draw copied it as `Decode(%)`. go vet named the file, the line and the offending verb, and
the fix loop burned two rounds and zero model calls without repairing one missing character.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from builder import _fix_bad_format_verb  # noqa: E402


def _file(line: str, n: int = 71) -> dict[str, str]:
    """A file whose line `n` is `line` — the gate is addressed by line number."""
    return {"x_test.go": "".join("package main\n" for _ in range(n - 1)) + line + "\n"}


VET = "./x_test.go:71:20: (*testing.common).Errorf format %) has unknown verb )"


def test_dropped_verb_gets_one_back():
    """More args than verbs -> the `%` was meant to consume one. The live case."""
    src = _file('\tt.Errorf("Decode(%) = %v, want %v", "!", err, ErrBadCode)')
    out = _fix_bad_format_verb(src, VET)
    assert out["x_test.go"].splitlines()[70].strip() == (
        't.Errorf("Decode(%v) = %v, want %v", "!", err, ErrBadCode)'
    )


def test_literal_percent_gets_escaped():
    """Args already match the verbs -> nothing was dropped, the percent is literal."""
    src = _file('\tt.Errorf("100%) done")')
    out = _fix_bad_format_verb(src, VET)
    assert out["x_test.go"].splitlines()[70].strip() == 't.Errorf("100%%) done")'


def test_ambiguous_arity_is_left_alone():
    """Neither reading fits, so the gate does nothing and the build error stands.

    A repair that guessed here would turn a build error into a silently wrong message,
    which is strictly worse than the error it replaces.
    """
    src = _file('\tt.Errorf("a %) b %v c %v", one, two, three, four)')
    assert _fix_bad_format_verb(src, VET) == {}


def test_alphanumeric_unknown_verb_is_a_different_mistake():
    """`%z` means the model chose a verb that does not exist.

    Inserting a `v` would produce `%vz` and print a stray letter forever — a build error
    replaced by a permanent cosmetic bug.
    """
    src = _file('\tt.Errorf("a %z", one)')
    out = "./x_test.go:71:20: (*testing.common).Errorf format %z has unknown verb z"
    assert _fix_bad_format_verb(src, out) == {}


def test_line_count_is_preserved():
    """It is registered as a PHASE 1 gate, which is a promise about line numbers.

    Phase 1 gates run together and every one of them is indexed by a line number the
    compiler just produced. A gate that added or removed a line there would invalidate the
    numbers for every gate behind it — the failure that once turned a struct literal into
    `tk1, _ := models.Task{...}` and cost a whole fix budget.
    """
    src = _file('\tt.Errorf("Decode(%) = %v", "!", err)')
    out = _fix_bad_format_verb(src, VET)
    assert len(out["x_test.go"].splitlines()) == len(src["x_test.go"].splitlines())


def test_reject_nothing_pin():
    """A correct format string must produce NO repair, whatever vet said."""
    src = _file('\tt.Errorf("Decode(%q) = %v", code, err)')
    assert _fix_bad_format_verb(src, VET) == {}
    assert _fix_bad_format_verb(src, "") == {}
