"""mirror_gap: a spec that mirrors an implementation but not its tests.

Synthetic specs on purpose. Asserting against taskflow and taskapi would pin the CORPUS's
current state — so fixing taskflow's spec, which is the whole point of finding the hole,
would break the test. What needs pinning is the detector: mirrored code plus mirrored
tests is fine, mirrored code plus a thin test list is not.
"""

from __future__ import annotations

from _named_test_audit import mirror_gap

MIRRORED_CODE = (
    "CreateTask(t) error, GetTask(id), ListTasks(), DeleteTask(id) error "
    "and the same four for Project.\n"
)
TASK_TESTS = " ".join(f"TestTask{n}:" for n in "ABCDEFGH")
PROJECT_TESTS = " ".join(f"TestProject{n}:" for n in "ABCDEFGH")


def test_mirrored_code_without_mirrored_tests_is_flagged():
    gap = mirror_gap(MIRRORED_CODE + TASK_TESTS + " TestProjectA:")
    assert gap is not None
    entity, primary, mirror = gap
    assert entity == "Project"
    assert primary == 8 and mirror == 1


def test_mirroring_both_is_not_flagged():
    """taskapi's shape: same idiom, tests named on both sides. The idiom is not the defect."""
    assert mirror_gap(MIRRORED_CODE + TASK_TESTS + " " + PROJECT_TESTS) is None


def test_a_spec_with_no_mirror_language_is_not_flagged():
    assert mirror_gap("CreateTask(t) error. " + TASK_TESTS) is None


def test_half_is_the_boundary_and_it_is_inclusive():
    """Four of eight passes, three of eight flags — pinned so the threshold cannot drift
    silently, since a detector that flags everything is as useless as one that flags
    nothing."""
    four = " ".join(f"TestProject{n}:" for n in "ABCD")
    three = " ".join(f"TestProject{n}:" for n in "ABC")
    assert mirror_gap(MIRRORED_CODE + TASK_TESTS + " " + four) is None
    assert mirror_gap(MIRRORED_CODE + TASK_TESTS + " " + three) is not None
