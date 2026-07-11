"""A green build is not the same as the project that was asked for.

The plan splits a package: store.go declares the interface, memory.go implements
it. The model writes both in store.go, memory.go has nothing left to declare, and
it ships as a bare `package store`. Go's compilation unit is the package, not the
file, so the build is green and nothing complains. Every multi-package artifact in
the suite carries one of these, and telling the model to stay in its lane did not
stop it — so it gets a repair.

Moving a declaration between files of the same package cannot change what the
program means. That is what makes this safe rather than clever.
"""

import shutil

import pytest

from src.builder import (
    FileSpec,
    GoToolchain,
    Spec,
    _fill_empty_planned_files,
    empty_go_files,
)

pytestmark = pytest.mark.skipif(
    shutil.which("go") is None, reason="needs the Go toolchain"
)

GO_MOD = "module guildlm.dev/plan\n\ngo 1.22\n"

# store.go over-reaches: it declares the interface (its job) AND MemStore
# (memory.go's job), using imports memory.go will need to take with it.
STORE = """package store

import (
	"errors"
	"sort"
	"sync"
)

var ErrNotFound = errors.New("not found")

type Task struct{ ID string }

type Store interface {
	Get(id string) (Task, error)
	List() []Task
}

type MemStore struct {
	mu    sync.RWMutex
	tasks map[string]Task
}

func NewMemStore() *MemStore { return &MemStore{tasks: map[string]Task{}} }

func (m *MemStore) Get(id string) (Task, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	t, ok := m.tasks[id]
	if !ok {
		return Task{}, ErrNotFound
	}
	return t, nil
}

func (m *MemStore) List() []Task {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]Task, 0, len(m.tasks))
	for _, t := range m.tasks {
		out = append(out, t)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}
"""

MEMORY_EMPTY = "package store\n"

SPEC = Spec(
    name="plan",
    description="d",
    go_module="guildlm.dev/plan",
    files=(
        FileSpec(
            path="store/store.go",
            purpose="package store. A Store interface and the ErrNotFound sentinel.",
        ),
        FileSpec(
            path="store/memory.go",
            purpose="package store. A goroutine-safe MemStore struct implementing "
            "the Store interface.",
        ),
    ),
)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD)
    (tmp_path / "store").mkdir()
    (tmp_path / "store" / "store.go").write_text(STORE)
    (tmp_path / "store" / "memory.go").write_text(MEMORY_EMPTY)
    return tmp_path


def test_the_dead_file_is_filled_and_the_project_stays_green(project):
    written = {"store/store.go": STORE, "store/memory.go": MEMORY_EMPTY}
    assert empty_go_files(written) == ["store/memory.go"]

    _fill_empty_planned_files(SPEC, written, project, GoToolchain())

    assert empty_go_files(written) == []
    assert "type MemStore struct" in written["store/memory.go"]
    assert "func NewMemStore()" in written["store/memory.go"]
    assert "func (m *MemStore) Get" in written["store/memory.go"]
    # It takes exactly the imports it uses, and no others.
    assert '"sync"' in written["store/memory.go"]
    assert '"sort"' in written["store/memory.go"]

    # The interface and the sentinel stay where the plan put them...
    assert "type Store interface" in written["store/store.go"]
    assert "ErrNotFound" in written["store/store.go"]
    assert "type MemStore struct" not in written["store/store.go"]
    # ...and store.go sheds the imports it no longer uses, or it will not compile.
    assert '"sync"' not in written["store/store.go"]

    ok, out = GoToolchain().check(project)
    assert ok, out


def test_the_interface_is_not_dragged_along(project):
    # memory.go's purpose MENTIONS Store because it implements it. Declaring Store
    # is store.go's job, and moving it would not fix the plan, it would break it
    # the other way.
    written = {"store/store.go": STORE, "store/memory.go": MEMORY_EMPTY}
    _fill_empty_planned_files(SPEC, written, project, GoToolchain())
    assert "type Store interface" not in written["store/memory.go"]


def test_a_file_that_declares_something_is_left_alone(project):
    written = {
        "store/store.go": STORE,
        "store/memory.go": "package store\n\ntype Other struct{}\n",
    }
    before = dict(written)
    _fill_empty_planned_files(SPEC, written, project, GoToolchain())
    assert written == before
