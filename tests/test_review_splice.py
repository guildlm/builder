"""_splice_fragment: put a review reply that is only the fixed functions back in the file.

The review specialist answers like a human reviewer — prose, then the function it fixed —
even though the prompt asks for the complete file. Writing that over the file destroyed it
and, in package main, did so INVISIBLY: goimports synthesises a `package main` clause for a
bare fragment, so the truncated file compiles and the non-regressing guard sees no
regression (logs/FINDING-review-pass-returns-fragments.txt).

These pin the contract, which is narrow on purpose: only funcs, and only ones that already
exist. Everything else returns None and is discarded exactly as before.
"""

from __future__ import annotations

import shutil

import pytest

from src.builder import (
    FakeCoder,
    FileSpec,
    GoToolchain,
    Spec,
    _func_blocks,
    _review_pass,
    _splice_fragment,
    plan,
)

GO = shutil.which("go")
requires_go = pytest.mark.skipif(GO is None, reason="go toolchain not installed")

ORIGINAL = (
    "package svc\n"
    "\n"
    "import \"errors\"\n"
    "\n"
    "// Store keeps things.\n"
    "type Store struct{ n int }\n"
    "\n"
    "func (s *Store) Bump() int {\n"
    "\ts.n++\n"
    "\treturn s.n\n"
    "}\n"
    "\n"
    "func Helper() error {\n"
    "\treturn errors.New(\"x\")\n"
    "}\n"
)


def test_replaces_a_method_and_keeps_everything_else():
    frag = "func (s *Store) Bump() int {\n\ts.n += 2\n\treturn s.n\n}\n"
    out, _why = _splice_fragment(frag, ORIGINAL)

    assert out is not None
    assert out.startswith("package svc"), "the package clause survives"
    assert "import \"errors\"" in out and "type Store struct" in out
    assert "func Helper() error" in out, "untouched declarations are still there"
    assert "s.n += 2" in out and "s.n++" not in out, "the method body was replaced"


def test_replaces_a_plain_func_too():
    frag = "func Helper() error {\n\treturn nil\n}\n"
    out, _why = _splice_fragment(frag, ORIGINAL)

    assert out is not None and "return nil" in out
    assert "func (s *Store) Bump()" in out


def test_a_fragment_that_ADDS_a_function_is_refused_and_says_why():
    """An addition has no unambiguous insertion point, and nothing says the rest of the
    file is still what the reviewer saw. Refusing is the whole difference from guessing.

    The REASON matters as much as the refusal: measured on shortener, this case is
    overwhelmingly the reviewer answering about a sibling file it was shown as context,
    and a log line that says "adds or redefines more than functions" hides that."""
    frag = "func BrandNew() int {\n\treturn 1\n}\n"
    out, why = _splice_fragment(frag, ORIGINAL)
    assert out is None
    assert "BrandNew" in why and "different file" in why


def test_a_fragment_carrying_more_than_functions_is_refused():
    """An import or a type is not a replacement — merging it means deciding where it goes."""
    frag = "import \"fmt\"\n\nfunc Helper() error {\n\treturn fmt.Errorf(\"x\")\n}\n"
    out, why = _splice_fragment(frag, ORIGINAL)
    assert out is None and "more than functions" in why


def test_prose_only_reply_is_refused():
    out, why = _splice_fragment("looks fine to me\n", ORIGINAL)
    assert out is None and "no functions" in why


def test_multi_line_signature_keeps_its_body():
    """The opening brace can sit below the func keyword; stopping at the first line
    would splice a signature and orphan the body — the same care strip_redeclarations
    needed."""
    original = (
        "package svc\n\nfunc Long(\n\ta int,\n\tb int,\n) int {\n\treturn a + b\n}\n"
    )
    frag = "func Long(\n\ta int,\n\tb int,\n) int {\n\treturn a * b\n}\n"
    out, _why = _splice_fragment(frag, original)

    assert out is not None
    assert "return a * b" in out and "return a + b" not in out
    assert out.count("func Long(") == 1, "the old block was replaced, not duplicated"
    assert len(_func_blocks(out)) == 1


@requires_go
def test_review_pass_now_applies_a_spliced_fix(tmp_path):
    """End to end with real go: the fragment shape that used to be discarded now lands.

    The reviewer returns only the fixed function, as the real specialist does. The pass
    must splice it, keep the file whole, and apply it because the project stays green.
    """
    spec = Spec(
        name="demo", description="a demo", go_module="example.com/demo",
        files=(FileSpec(path="go.mod", purpose="module file"),
               FileSpec(path="calc.go", purpose="Double returns 2n")),
    )
    go_mod = "module example.com/demo\n\ngo 1.23\n"
    buggy = "package main\n\nfunc Double(n int) int {\n\treturn n + 2\n}\n\nfunc main() {}\n"
    (tmp_path / "go.mod").write_text(go_mod)
    (tmp_path / "calc.go").write_text(buggy)
    written = {"go.mod": go_mod, "calc.go": buggy}
    reviewer = FakeCoder({"calc.go": [
        "Bug: Double adds instead of multiplying.\n\n"
        "```go\nfunc Double(n int) int {\n\treturn n * 2\n}\n```"
    ]})

    _review_pass(spec, plan(spec), written, tmp_path, GoToolchain(), reviewer, rounds=1)

    landed = (tmp_path / "calc.go").read_text()
    assert "return n * 2" in landed, "the review fix was applied"
    assert landed.lstrip().startswith("package main"), "the file is still a file"
    assert "func main()" in landed, "the rest of the file survived the splice"
    assert written["calc.go"] == landed, "`written` tracks what landed on disk"
