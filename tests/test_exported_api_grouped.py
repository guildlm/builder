"""exported_api() must show a cross-package consumer the GROUPED var/const members too.

WHY THIS EXISTS. `exported_api` builds the summary another package sees when it imports this
one. It kept single-line `var ErrX = ...` and dropped every member of

    var (
        ErrInvalid = errors.New("invalid")
        ...
    )

in full — `(?:var|const)\\s+(\\w+)` cannot match `var (`, and the block-spanning counter tracks
{} rather than (), so the members were then skipped one by one for not starting with a keyword.
Sentinel errors are almost always written in the grouped form, so a consumer saw NONE of them
and had nothing to reconcile its own guess against.

THE DEFECT IT ADDRESSES, measured BEFORE the change and pre-registered:
logs/PREREG-expose-grouped-sentinels-in-the-cross-package-api-block.txt — of 50 snapshotted
trees, 29 make a cross-package sentinel reference and 20 of those (69%) name a sentinel that
does not exist; the fix loop repairs 12 and 8 stay fatal.

⚠️ WHAT THESE TESTS DO AND DO NOT CLAIM. They pin the EXTRACTOR: the names are now in the
block. Whether the model then USES the name it is shown instead of one it derives from prose is
the pre-registered draw endpoint and needs a server — it is NOT established here. An extractor
test passing is not the fix working.
"""

import sys

sys.path.insert(0, "src")

from src.builder import exported_api

GROUPED = '''package models

import "errors"

var (
	ErrInvalid           = errors.New("invalid")
	ErrNotFound          = errors.New("not found")
	ErrInsufficientFunds = errors.New("insufficient funds")
	errInternal          = errors.New("internal")
)
'''


def _names(code: str) -> list[str]:
    return [ln.strip() for ln in exported_api(code).splitlines() if ln.startswith("\t")]


def test_grouped_exported_members_are_visible():
    assert _names(GROUPED) == ["ErrInvalid", "ErrNotFound", "ErrInsufficientFunds"]


def test_unexported_members_stay_hidden():
    """The whole point of the summary is the EXPORTED surface. A grouped block that leaks
    unexported names would invite a consumer to reference something it cannot see."""
    assert "errInternal" not in exported_api(GROUPED)


def test_values_are_dropped_but_names_kept():
    """Names, not bodies — the summary must stay cheap. If the values came through, every
    consumer prompt would carry the whole error table."""
    api = exported_api(GROUPED)
    assert "errors.New" not in api
    assert 'insufficient funds' not in api


def test_the_single_line_form_is_unchanged():
    """The regression direction. Single-line vars already worked and must keep working."""
    api = exported_api('package m\n\nvar ErrSingle = errors.New("x")\n')
    assert "ErrSingle" in api
    assert "errors.New" not in api


def test_a_const_block_with_iota_keeps_its_type():
    """Consts frequently have no `=` at all after the first line. Splitting on `=` must not
    eat the members that never had one."""
    api = exported_api(
        "package k\n\nconst (\n\t// leading comment\n\tStatusOK Status = iota\n"
        "\tStatusBad\n\thidden\n)\n"
    )
    assert "StatusOK Status" in api
    assert "StatusBad" in api
    assert "hidden" not in api


def test_comments_inside_the_block_are_not_emitted_as_members():
    api = exported_api("package k\n\nvar (\n\t// ErrGhost is not a declaration\n\tErrReal = e()\n)\n")
    assert "ErrReal" in api
    assert "ErrGhost" not in api, "a comment mentioning a name must not become an exported name"


def test_a_shared_line_is_kept_when_any_name_is_exported():
    """`A, b = f()` declares both. Dropping the line to hide `b` would hide `A` as well;
    keeping it is the lesser error and is what the single-line branch already does."""
    assert "ErrA" in exported_api("package k\n\nvar (\n\tErrA, errB = f()\n)\n")


def test_an_entirely_unexported_block_emits_no_empty_wrapper():
    """A `var (` / `)` pair with nothing inside is noise in every consumer prompt."""
    api = exported_api("package k\n\nvar (\n\terrA = f()\n\terrB = f()\n)\n")
    assert "var (" not in api


def test_declarations_after_the_block_are_still_reached():
    """THE SCAN-POSITION CONTROL. The block advances the cursor to its closing paren; get
    that wrong by one and everything after the block silently vanishes from the summary —
    which is the same class of failure being fixed, one line lower."""
    api = exported_api(GROUPED + "\ntype Account struct {\n\tID string\n}\n\nfunc New() *Account { return nil }\n")
    assert "type Account struct" in api
    assert "func New() *Account" in api
    assert "return nil" not in api, "func bodies must still be elided"


def test_two_blocks_in_one_file():
    api = exported_api("package k\n\nvar (\n\tErrOne = f()\n)\n\nconst (\n\tTwo = 2\n)\n")
    assert "ErrOne" in api and "Two" in api
