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


# A deadlock is legal Go: it builds, it vets, and only `go test` finds it — by
# hanging. If the harness kills the test binary before Go prints its own timeout,
# the model is handed the sentence "`go test ./...` timed out" with no file, no
# line and no cause, and no model can repair that. Go, left to hit its OWN -timeout,
# dumps the goroutines and the dump names the two methods that deadlocked. The fix
# is to give `go test` a -timeout shorter than the subprocess timeout, and to keep
# whatever the process printed before it was killed.
DEADLOCK_STORE = """package main

import "sync"

type Store struct {
	mu   sync.RWMutex
	seen map[int]bool
}

func NewStore() *Store { return &Store{seen: map[int]bool{}} }

func (s *Store) Get(id int) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.seen[id]
}

func (s *Store) Add(id int) {
	s.mu.Lock()         // held across a call that takes RLock -> RWMutex is not reentrant
	defer s.mu.Unlock()
	_ = s.Get(id)
	s.seen[id] = true
}
"""


def test_a_deadlock_reaches_the_model_as_a_stack_trace_not_just_timed_out(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD)
    (tmp_path / "main.go").write_text(MAIN)
    (tmp_path / "store.go").write_text(DEADLOCK_STORE)
    (tmp_path / "deadlock_test.go").write_text(
        textwrap.dedent(
            """
            package main

            import "testing"

            func TestDeadlocks(t *testing.T) {
            	NewStore().Add(1)
            }
            """
        ).lstrip()
    )
    ok, out = GoToolchain().test(tmp_path)
    assert not ok
    # the whole point: the failure names WHERE, so a later round has something to fix
    assert "Add" in out and "Get" in out
    assert "RWMutex" in out or "sync." in out


def test_test_stage_repeats_the_suite():
    """`go test` must run the suite MORE THAN ONCE.

    One run is a sample, not a verdict: Go randomises map iteration per run, so a store
    that ignores its spec's "sorted by ID" passes about as often as it fails and the fix
    loop never sees a failure to fix. A tasks-api build shipped rc=0 exactly that way —
    re-running its suite afterwards gave 9 pass / 3 fail over 12.

    Pinned as a test because the flag is invisible in behaviour until the day it matters:
    a suite that passes looks identical whether it ran once or four times, so nothing else
    here would notice if the flag were dropped.
    """
    calls = []

    class Recorder(GoToolchain):
        def _run(self, args, cwd):
            calls.append(args)
            return True, ""

    Recorder().test("/tmp")
    assert calls, "test() did not invoke the toolchain at all"
    assert "-count=4" in calls[0], f"the suite is run only once: {calls[0]}"
    # Four runs share ONE budget, so the timeout must survive alongside the repeat.
    assert "-timeout" in calls[0], f"timeout dropped: {calls[0]}"


def test_var_t_redeclaration_is_repaired(tmp_path):
    """`var t Task` in a tester function must be repaired by the gate chain.

    Go reports this as "t redeclared in this block" — not as the "t.Fatalf undefined"
    that `t := ...` produces, and not as the assignment form either. The gate matched only
    the other two, and the AST tool behind it did not recognise a DeclStmt, so a tasks-api
    build spent 3381 seconds and eleven fix rounds red on one line while the spec forbade
    it in two separate places and the machinery that repairs the other two shapes sat
    unused.
    """
    (tmp_path / "go.mod").write_text("module guildlm.dev/x\n\ngo 1.23\n")
    (tmp_path / "task.go").write_text(textwrap.dedent("""
        package main

        type Task struct{ Title string }

        func (t Task) Valid() bool { return t.Title != "" }

        func main() {}
    """).lstrip())
    (tmp_path / "x_test.go").write_text(textwrap.dedent("""
        package main

        import "testing"

        func TestValidateOK(t *testing.T) {
            var t Task
            t.Title = "a"
            if !t.Valid() {
                t.Fatalf("want valid")
            }
        }
    """).lstrip())

    tc = GoToolchain()
    ok, out = tc.check(tmp_path)
    assert not ok and "redeclared" in out, f"fixture did not reproduce the error: {out[:200]}"

    written = {f.name: f.read_text() for f in tmp_path.glob("*.go")}
    changed = _run_deterministic_gates(written, out, "guildlm.dev/x")
    assert "x_test.go" in changed, "the gate did not touch the shadowing test file"
    for path, content in changed.items():
        (tmp_path / path).write_text(content)

    ok2, out2 = tc.check(tmp_path)
    assert ok2, f"still broken after the gate: {out2[:300]}"
    # the tester must survive: t.Fatalf still binds to *testing.T
    assert "t.Fatalf" in (tmp_path / "x_test.go").read_text()
