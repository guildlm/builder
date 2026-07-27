"""Every instrument must REFUSE a target that does not exist.

A checker whose failure mode is a plausible-looking clean result is worse than no checker,
and that is not hypothetical here. Probing all nine instruments with a nonexistent path
found FOUR answering about nothing with status 0: an unmatched spec name printing an empty
table, a typo'd selector reporting a clean teeth run, an unreadable file exiting green, and
a grader that took "--dir" as a directory name and printed "SKIPPED".

Empty input, unmatched selector and unreadable file all collapse into the output of a clean
result, because "no findings" is what clean looks like.

Pinned as a test because every one of those fixes is a few lines that a later edit can
quietly undo, and nothing else would notice: the tools keep working, they just stop
refusing. A tenth instrument written the same day this rule was established still ignored
its argv, which is the argument for a test rather than a habit.
"""

import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY_BIN = ROOT / ".venv" / "bin" / "python"

INSTRUMENTS = [
    "_hole_hunt.py", "_hole_closed.py", "_why_red.py", "score_backend.py",
    "_deadlock_detector.py", "_named_test_audit.py", "_teeth_suite.py",
    "_gate_audit.py", "_escalation_surface.py", "_registry_drift.py",
    "_mapsort_audit.py", "_test_durability.py", "_candidate_triage.py",
    "_redraw_diff.py", "_restore_gomod.py", "_spec_count_audit.py",
    "_unnamed_tests.py", "_bound_probe.py", "_mirror_calls_audit.py",
]


# _corpus_state.py is deliberately NOT here. Its argument is a path to COMPARE against the
# live writers, not a target to read: "nothing is generating /nonexistent-xyz" is a correct
# and useful answer, so demanding a refusal would be demanding the wrong behaviour. Added to
# the list once and it failed immediately, which is the list working.


@pytest.mark.parametrize("tool", INSTRUMENTS)
def test_instrument_refuses_a_target_that_does_not_exist(tool):
    path = ROOT / tool
    if not path.exists():
        pytest.skip(f"{tool} not present")
    proc = subprocess.run(
        [str(PY_BIN) if PY_BIN.exists() else "python3", str(path), "/nonexistent-xyz"],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
    )
    assert proc.returncode != 0, (
        f"{tool} answered a question about a path that does not exist and exited 0.\n"
        f"stdout: {proc.stdout[-400:]}"
    )
