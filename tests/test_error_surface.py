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


def _drive_to_fixpoint(project, tc, rounds=6):
    """What the fix loop actually does: repair, re-compile, repair again. The
    gates deliberately apply at most ONE line-shifting change per pass — a gate
    that inserts a line invalidates the compiler's line numbers for every gate
    behind it — so reaching everything takes more than one pass, by design."""
    for _ in range(rounds):
        written = {
            p.name: p.read_text() for p in project.glob("*.go")
        }
        ok, out = tc.check(project)
        if ok:
            break
        changed = _run_deterministic_gates(written, out, None)
        if not changed:
            break
        for name, code in changed.items():
            (project / name).write_text(code)
    return {p.name: p.read_text() for p in project.glob("*.go")}


def test_the_wider_surface_makes_the_hidden_defect_reachable(project):
    tc = GoToolchain()
    written = {"store.go": STORE, "store_test.go": STORE_TEST}

    # On the NARROW surface the shadow is not merely unrepaired — it is invisible.
    # vet stops at the first type error, so no gate can even see it.
    _, vet_out = tc.vet(project)
    assert "has no field or method Fatalf" not in vet_out
    narrow = _run_deterministic_gates(written, vet_out, None)
    assert "store_test.go" not in narrow

    # On the WIDE surface the loop reaches both defects and repairs both.
    final = _drive_to_fixpoint(project, tc)
    assert "func NewStore()" in final["store.go"]
    assert "for _, tk := range tasks" in final["store_test.go"]


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
