"""A gate cannot repair an error the compiler never printed.

Each Go stage shows a different slice of the truth: `go build` skips _test.go
files entirely, `go vet` typechecks them but bails at the FIRST type error in a
package, and `go test` compiles the test binary and reports up to ten errors.
So a failing check has to harvest all three, or a mechanical defect can sit
invisible behind an unrelated one for every round the loop has.
"""

import shutil
import textwrap

import pytest

from src.builder import GoToolchain, _run_deterministic_gates

pytestmark = pytest.mark.skipif(
    shutil.which("go") is None, reason="needs the Go toolchain"
)

GO_MOD = "module guildlm.dev/surface\n\ngo 1.22\n"

MAIN = "package main\n\nfunc main() {}\n"

# The store names its constructor NewMemStore; everything else calls NewStore.
STORE = """package main

type Task struct {
	ID    int
	Title string
}

type MemStore struct{ tasks map[int]Task }

func NewMemStore() *MemStore { return &MemStore{tasks: map[int]Task{}} }

func (s *MemStore) Create(t Task) error { s.tasks[t.ID] = t; return nil }
"""

# Two independent defects: the undefined constructor (which vet stops on) and,
# hidden behind it, a loop variable shadowing the tester.
STORE_TEST = """package main

import "testing"

func TestCreate(t *testing.T) {
	s := NewStore()
	tasks := []Task{{ID: 1, Title: "a"}}
	for _, t := range tasks {
		if err := s.Create(t); err != nil {
			t.Fatalf("create: %v", err)
		}
	}
}
"""


@pytest.fixture
def project(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD)
    (tmp_path / "main.go").write_text(MAIN)
    (tmp_path / "store.go").write_text(STORE)
    (tmp_path / "store_test.go").write_text(STORE_TEST)
    return tmp_path


def test_check_surfaces_errors_that_vet_alone_hides(project):
    tc = GoToolchain()

    # `go vet` stops at the first type error, so the shadow is invisible.
    _, vet_out = tc.vet(project)
    assert "undefined: NewStore" in vet_out
    assert "Fatalf" not in vet_out

    # check() harvests test's wider diagnostics, so BOTH defects are visible.
    ok, out = tc.check(project)
    assert not ok
    assert "undefined: NewStore" in out
    assert "has no field or method Fatalf" in out


def test_the_wider_surface_lets_more_gates_fire_in_one_round(project):
    tc = GoToolchain()
    written = {
        "store.go": STORE,
        "store_test.go": STORE_TEST,
    }

    _, vet_out = tc.vet(project)
    narrow = _run_deterministic_gates(written, vet_out, None)
    _, wide_out = tc.check(project)
    wide = _run_deterministic_gates(written, wide_out, None)

    # On the narrow surface only the constructor can be repaired; the shadow is
    # unreachable. On the wide one the loop clears both in the SAME round.
    assert set(narrow) == {"store.go"}
    assert set(wide) == {"store.go", "store_test.go"}
    assert "func NewStore()" in wide["store.go"]
    assert "for _, tk := range tasks" in wide["store_test.go"]


def test_a_green_project_still_reports_green(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD)
    (tmp_path / "main.go").write_text(MAIN)
    (tmp_path / "store.go").write_text(STORE)
    (tmp_path / "ok_test.go").write_text(
        textwrap.dedent(
            """
            package main

            import "testing"

            func TestOK(t *testing.T) {
            	s := NewMemStore()
            	if err := s.Create(Task{ID: 1}); err != nil {
            		t.Fatalf("create: %v", err)
            	}
            }
            """
        ).lstrip()
    )
    ok, out = GoToolchain().check(tmp_path)
    assert ok, out
