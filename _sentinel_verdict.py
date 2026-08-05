#!/usr/bin/env python3
"""Classify one models.go by which insufficient-funds sentinel it declares.

    ./_sentinel_verdict.py <path-to-models.go>     -> prints LONG | ABBREVIATED:<name> | ABSENT
    ./_sentinel_verdict.py --self-test

WHY THIS IS A FILE AND NOT SIX LINES INSIDE _probe_process_sentinel.sh, which is where it
started. It was validated against the four known trees by RE-TYPING the logic into a throwaway
snippet — so what passed was a COPY, and the copy and the original were free to drift from the
moment they were written. This campaign has a standing rule about that (a hand-retyped snippet
must never produce a table column) and `_selftest_freeze_guard.sh` already follows the fix:
extract the lines from the real thing rather than transcribing them. Same move here — the probe
script now CALLS this, so the tested code and the used code are one object.

THE VERDICT DRIVES SELECTION, which is why it is worth this much care: LONG means the process
is discarded and re-probed, and a classifier that said LONG too readily would quietly select for
whatever it was confusing with LONG.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

from builder import top_level_decls  # noqa: E402


def verdict(code: str) -> str:
    """LONG / ABBREVIATED:<names> / ABSENT, from the file's top-level declarations.

    Uses top_level_decls rather than a regex so that GROUPED `var (...)` blocks count — every
    ledger models.go writes its sentinels grouped, and a regex that missed them would call
    every tree ABSENT. That is not hypothetical: exported_api() had exactly that bug until
    5 August, in this same repo, for grouped blocks.
    """
    errs = {d for d in top_level_decls(code) if d.startswith("Err")}
    ins = sorted(e for e in errs if "Insuffic" in e)
    if not ins:
        return "ABSENT"
    if ins == ["ErrInsufficientFunds"]:
        return "LONG"
    return "ABBREVIATED:" + ",".join(ins)


def self_test() -> int:
    ok = True

    def chk(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {name}: {got!r} != {want!r}")

    GROUPED = ("package models\n\nimport \"errors\"\n\nvar (\n"
               "\tErrInvalid = errors.New(\"invalid\")\n"
               "\tErrNotFound = errors.New(\"nf\")\n"
               "\t%s\n)\n")
    chk("grouped long", verdict(GROUPED % 'ErrInsufficientFunds = errors.New("insufficient funds")'), "LONG")
    chk("grouped abbreviated",
        verdict(GROUPED % 'ErrInsufficient = errors.New("insufficient funds")'),
        "ABBREVIATED:ErrInsufficient")
    chk("grouped absent", verdict(GROUPED % 'ErrUnbalanced = errors.New("unbalanced")'), "ABSENT")

    # single-line form must classify identically — the shape varies across processes
    chk("single-line long",
        verdict('package m\n\nvar ErrInsufficientFunds = errors.New("insufficient funds")\n'), "LONG")

    # a file with NO sentinels at all is ABSENT, not an error
    chk("no sentinels", verdict("package m\n\ntype T struct{}\n"), "ABSENT")

    # ⚠️ THE ONE THAT MATTERS FOR SELECTION: a grouped block must never read as ABSENT. If it
    # did, every process would look informative and the discard step would silently stop working.
    chk("grouped is not ABSENT",
        verdict(GROUPED % 'ErrInsufficientFunds = errors.New("x")') != "ABSENT", True)

    # both names present (seen in repaired trees) is not LONG — LONG means the long name ALONE
    chk("both names is not LONG",
        verdict(GROUPED % 'ErrInsufficientFunds = errors.New("x")\n\tErrInsufficient = errors.New("y")'),
        "ABBREVIATED:ErrInsufficient,ErrInsufficientFunds")

    print("  self-test: OK — grouped and single-line agree, absent separated, a grouped block "
          "never reads as ABSENT" if ok else "  self-test: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(verdict(pathlib.Path(sys.argv[1]).read_text()))
