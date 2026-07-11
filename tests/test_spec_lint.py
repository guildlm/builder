"""Spec lint — catch a spec that no implementation could satisfy, before the run.

Every rule here is a failure that actually happened, cost a full generation, and
was diagnosed only by reading the artifact afterwards. All of them were sitting
in the YAML the whole time.
"""

from src.builder import FileSpec, Spec, lint_spec


def spec(*files: FileSpec) -> Spec:
    return Spec(name="x", description="d", files=files)


def test_flags_a_fresh_instance_per_case_that_also_wants_a_duplicate():
    # Seen in SEVEN specs. On a store nobody wrote to there is nothing to
    # duplicate, so the case fails however correct the implementation is.
    s = spec(
        FileSpec(
            path="store_test.go",
            purpose="package store. Fresh NewMemStore per case. Cover create->nil "
            "then duplicate->ErrExists; Get present->value.",
        )
    )
    (problem,) = lint_spec(s)
    assert "precondition" in problem
    assert "store_test.go" in problem


def test_flags_the_other_phrasing_of_the_same_trap():
    # taskapi said it this way, and a regex written for only the first phrasing
    # walked straight past it.
    s = spec(
        FileSpec(
            path="router_test.go",
            purpose="Each case builds a FRESH router+store. Cover: duplicate id -> "
            "409; GET existing -> 200.",
        )
    )
    assert lint_spec(s)


def test_accepts_a_fresh_instance_per_case_that_seeds_itself():
    # The fixed shape must NOT be flagged, or the rule is just noise.
    s = spec(
        FileSpec(
            path="store_test.go",
            purpose="Each function builds its OWN fresh NewMemStore. A fresh store "
            "is EMPTY, so create the precondition first: TestCreateDuplicate "
            "creates ONCE, then creates the SAME id again -> ErrExists. "
            "TestGetExisting creates FIRST, then gets it.",
        )
    )
    assert lint_spec(s) == []


def test_flags_a_test_calling_a_constructor_nobody_declares():
    # tasks-api burned five fix rounds on `undefined: NewStore`.
    s = spec(
        FileSpec(path="store.go", purpose="A store built by NewMemStore()."),
        FileSpec(path="store_test.go", purpose="Tests calling NewStore()."),
    )
    (problem,) = lint_spec(s)
    assert "NewStore" in problem and "undefined" in problem


def test_does_not_flag_a_stdlib_constructor():
    # httptest.NewRecorder and slog.NewTextHandler are not ours to declare —
    # matching them turns the rule into noise and it fired on four specs.
    s = spec(
        FileSpec(path="router.go", purpose="A router built by NewRouter()."),
        FileSpec(
            path="router_test.go",
            purpose="Tests against NewRouter(slog.New(slog.NewTextHandler(io.Discard, "
            "nil))), using httptest.NewRecorder() and httptest.NewRequest().",
        ),
    )
    assert lint_spec(s) == []


def test_flags_one_name_asked_to_be_both_an_interface_and_a_struct():
    s = spec(
        FileSpec(
            path="store.go",
            purpose="Declare a Store interface with the methods, and a Store struct "
            "implementing it.",
        )
    )
    (problem,) = lint_spec(s)
    assert "redeclared" in problem


def test_flags_a_spec_that_forbids_the_models_idiom():
    # tasks-api told store.go to be a concrete struct and "do NOT model it as an
    # interface". The model wrote the interface anyway in all five rolls; the ban
    # only decided HOW it broke.
    s = spec(
        FileSpec(
            path="store.go",
            purpose="A thread-safe Store — a single CONCRETE struct (do NOT model "
            "it as an interface), built by NewStore().",
        )
    )
    (problem,) = lint_spec(s)
    assert "interface" in problem


def test_the_whole_current_suite_is_clean():
    import pathlib

    flagged = {
        p.name: lint_spec(Spec.from_yaml(p))
        for p in sorted(pathlib.Path("specs").glob("*.yaml"))
    }
    assert not {k: v for k, v in flagged.items() if v}, flagged
