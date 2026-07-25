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

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN = ROOT / "generated"


def test_at_least_one_artifact_has_a_red_baseline():
    if not GEN.is_dir():
        pytest.skip("no generated/ corpus in this checkout")
    artifacts = sorted(GEN.glob("*-v4"))
    if not artifacts:
        pytest.skip("corpus is empty")
    red = []
    for art in artifacts:
        proc = subprocess.run(["go", "build", "./..."], cwd=art,
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
