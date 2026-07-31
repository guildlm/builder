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


# --------------------------------------------------------------------------- #
# ...and a build that never converges is still a build that lost a planned file.
#
# The repair and its warning both used to sit inside _finish_green, so the only
# projects ever CHECKED for plan conformance were the ones that had already
# passed. Measured on five draws: the three green ones logged the warning; the
# two that exhausted their fix budget shipped an empty planned file in total
# silence. This drives the whole of build() rather than the repair alone,
# because the defect was never in the repair — it was in where it was called.
# --------------------------------------------------------------------------- #

BROKEN_MAIN = """package main

import "guildlm.dev/conf/internal/store"

func main() {
	var s store.Store = store.NewMemStore()
	_ = s.NoSuchMethod()
}
"""

CONF_STORE = """package store

type Store interface {
	Get(id string) (string, error)
}

type MemStore struct{ items map[string]string }

func NewMemStore() *MemStore { return &MemStore{items: map[string]string{}} }

// undefinedHelper does not exist anywhere in the module: package store cannot
// compile, so neither can anything importing it, and no fix round can recover
// it from a coder that keeps answering with the same file.
func (m *MemStore) Get(id string) (string, error) { return undefinedHelper(m, id) }
"""

NOT_GREEN_SPEC = Spec(
    name="conf",
    description="d",
    go_module="guildlm.dev/conf",
    files=(
        FileSpec(path="go.mod", purpose="MARK_GOMOD. The module file."),
        FileSpec(
            path="internal/store/store.go",
            purpose="MARK_STORE. package store. A Store interface and a MemStore struct.",
        ),
        FileSpec(
            path="internal/store/memory.go",
            purpose="MARK_MEMORY. package store. Implements the `MemStore` type.",
        ),
        FileSpec(
            path="cmd/server/main.go",
            purpose="MARK_MAIN. package main with func main, wiring the store.",
        ),
    ),
)


class ScriptedCoder:
    """One canned answer per purpose marker. Anything else — every fix-loop
    request — comes back as a bare `package main`, so nothing it is asked to
    repair can compile and the build cannot converge."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str, temperature: float | None = None) -> str:
        self.prompts.append(prompt)
        if "MARK_STORE" in prompt:
            return CONF_STORE
        if "MARK_MEMORY" in prompt:
            return "package store\n"  # the sibling did its job; nothing left here
        if "MARK_MAIN" in prompt:
            return BROKEN_MAIN
        return "package main\n"


def test_the_empty_file_is_reported_even_when_the_build_never_goes_green(
    tmp_path, capsys
):
    from src.builder import build

    ok, written = build(
        NOT_GREEN_SPEC, ScriptedCoder(), tmp_path, max_fix_rounds=1,
        toolchain=GoToolchain(),
    )

    assert not ok, "the fixture is only meaningful if the build FAILS"
    assert "internal/store/memory.go" in empty_go_files(written)

    err = capsys.readouterr().err
    warned = [ln for ln in err.splitlines() if "does not match its own plan" in ln]
    assert any("internal/store/memory.go" in ln for ln in warned), (
        "a planned file came out empty and the failing build said nothing:\n" + err
    )
    # and it says which kind of build it was, so a log reader is not left to
    # infer that "shipped" meant something that never shipped
    assert any("never went green" in ln for ln in warned), warned
