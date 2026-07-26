"""The corpus must keep at least one artifact whose baseline is already red.

_teeth_suite's central rule is that a mutation on an artifact that ALREADY fails is not a
CAUGHT — the verdict is void. tasks-api-min-v4 and tasks-api-noshadownudge-v4 are the only
inputs in generated/ that exercise it: between them they account for every BASELINE-RED
row in the corpus sweep and produce no CAUGHT or SURVIVED at all.

They look exactly like rot — two archives of runs the builder gave up on, sitting beside
successful ones and inflating probe counts. Tidying them away would leave the rule in
place, passing review, and never executed by anything. A green suite would not notice,
because a check that stops running looks like a check that finds nothing.

This does not care WHICH artifacts they are. Regenerating both is fine, as long as
something still fails to build.
"""

import pathlib
import subprocess
import tempfile

import pytest

import os

ROOT = pathlib.Path(__file__).resolve().parent.parent
# The corpus directory is overridable so this test can be PROVEN to fire. It was committed
# without that proof, against the standard applied to every other check today — and a test
# nobody has watched fail is the exact thing it exists to prevent.
GEN = pathlib.Path(os.environ.get("GUILDLM_CORPUS", ROOT / "generated"))


def test_at_least_one_artifact_has_a_red_baseline():
    if not GEN.is_dir():
        pytest.skip("no generated/ corpus in this checkout")
    # AN EMPTY DIRECTORY IS NOT A RED BASELINE. `go build ./...` in a directory with no Go
    # files fails too, so this check went on passing after I emptied 136 artifacts with a
    # careless glob — 21 of the 25 -v4 trees had no code left at all, and every one of them
    # counted as "fails to build". The rule it guards needs an artifact that COMPILES
    # WRONG, not one with nothing to compile; absence and failure are different things, the
    # same distinction _gate_audit.archived_failures() already draws for kill-debris.
    artifacts = [d for d in sorted(GEN.glob("*-v4")) if any(d.rglob("*.go"))]
    if not artifacts:
        pytest.skip("corpus is empty")
    red = []
    # -o <tmpdir>: `go build ./...` in a main package WRITES THE EXECUTABLE INTO THE
    # CURRENT DIRECTORY, so this check was leaving an 8MB binary inside every service
    # artifact it inspected — nine of them, ~74MB, straight into the corpus it audits.
    # Traced from the other end: the artifacts' directory mtimes were all stamped with the
    # minute this suite last ran, which is how a corpus that nothing should be writing to
    # started looking freshly touched. (_gate_audit already strips "stray compiled
    # binaries" from its copies; this is where they came from.) The one instrument that
    # infers a tree's age reads *.go only, so no published number moved — but a test that
    # writes into the corpus is a measurement waiting to be wrong.
    with tempfile.TemporaryDirectory() as out:
        for art in artifacts:
            proc = subprocess.run(["go", "build", "-o", out, "./..."], cwd=art,
                                  capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                red.append(art.name)
    assert red, (
        "Every artifact in generated/ builds, so nothing exercises the BASELINE-RED path.\n"
        "That path implements the rule that a mutation on an already-failing artifact is a\n"
        "VOID verdict, not a CAUGHT. With no red-baseline input the rule still exists and\n"
        "is never executed — and a green suite cannot tell that apart from it working.\n"
        "If you regenerated or removed tasks-api-min-v4 / tasks-api-noshadownudge-v4,\n"
        "keep (or plant) one artifact that fails to build."
    )
