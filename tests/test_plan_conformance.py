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


# --------------------------------------------------------------------------- #
# The gate demanded the over-reach it repairs.
#
# `required = _required_decls(purpose) - sibling_decls` arbitrates ownership
# ACROSS packages only. Inside a package the only arbitration was which file got
# written first, so whichever of an interface/implementer pair came first was
# required to declare the other's type. Every spec has exactly one such symbol
# and it is always the same one: memory.go required to declare Store.
#
# The specs already settle it in plain English, so the rule reads the disclaimer.
# Both tests below are traps a plausible implementation falls into — the first
# one silently did nothing, the second silently disarmed the owner.
# --------------------------------------------------------------------------- #

from src.builder import _disclaimed_decls  # noqa: E402


def _files(*pairs):
    return [FileSpec(path=p, purpose=q) for p, q in pairs]


IMPL_PURPOSE = (
    "package store. `MemStore` — the in-memory implementation of the Store "
    "interface declared in store.go IN THIS SAME PACKAGE. It must implement "
    "EVERY method of that interface; a missing method is a compile error at the "
    "first assignment to a Store variable."
)
OWNER_PURPOSE = "package store. The Store INTERFACE only — no implementation in this file."


def test_the_implementer_is_not_asked_to_declare_the_interface():
    files = _files(("store/store.go", OWNER_PURPOSE), ("store/memory.go", IMPL_PURPOSE))
    assert _disclaimed_decls(files, "store/memory.go", IMPL_PURPOSE) == {"Store"}


def test_a_bare_reference_elsewhere_in_the_purpose_does_not_veto_it():
    # IMPL_PURPOSE's last sentence mentions "a Store variable" with no disclaimer.
    # Requiring EVERY mention to disclaim let that sentence veto the rule, and the
    # fix did nothing at all on any spec. Only the sentence that MADE the promise
    # — the one the extractor fires on — can take it back.
    assert "Store" in _disclaimed_decls(
        _files(("store/store.go", OWNER_PURPOSE), ("store/memory.go", IMPL_PURPOSE)),
        "store/memory.go", IMPL_PURPOSE,
    )


def test_the_owner_keeps_its_own_type_even_when_it_disclaims_another():
    # taskapi's store.go says "use models.Task / models.Project (qualified — do
    # NOT redeclare them here)" about the MODELS types, in a different sentence
    # from the one declaring Store. A purpose-wide match disarms the owner too,
    # which is the pre-registered reject condition.
    owner = (
        "package store. Import the models package and use models.Task / "
        "models.Project (qualified — do NOT redeclare them here). A Store "
        "INTERFACE with CreateTask(models.Task) error."
    )
    files = _files(("store/store.go", owner), ("store/memory.go", IMPL_PURPOSE))
    assert _disclaimed_decls(files, "store/store.go", owner) == set()


def test_an_unambiguous_type_is_never_dropped():
    # MemStore is claimed by no sibling, so no amount of "implementation of"
    # prose may talk this file out of declaring it.
    files = _files(("store/store.go", OWNER_PURPOSE), ("store/memory.go", IMPL_PURPOSE))
    assert "MemStore" not in _disclaimed_decls(files, "store/memory.go", IMPL_PURPOSE)


def test_a_sibling_in_another_package_is_not_a_tie():
    # cross-package ownership is _foreign_owned_decls' job, and this must not
    # start second-guessing it: same NAME, different directory, no tie to break.
    files = _files(("store/store.go", OWNER_PURPOSE), ("api/handler.go", IMPL_PURPOSE))
    assert _disclaimed_decls(files, "api/handler.go", IMPL_PURPOSE) == set()


# --------------------------------------------------------------------------- #
# The gate on the move itself: no NEW error, rather than no error at all.
#
# Measured on the corpus: 59 of 74 cases had a donor and a symbol to move and
# reverted anyway, because the project was already red for reasons the move
# neither caused nor could fix. The comparison that makes the weaker gate safe
# has one hard requirement — line numbers must not be part of it, since moving
# declarations shifts every line after them.
# --------------------------------------------------------------------------- #

from src.builder import _error_keys  # noqa: E402


def test_the_same_error_at_a_different_line_is_not_a_new_error():
    before = _error_keys("store/store.go:41:2: undefined: helper\n")
    after = _error_keys("store/store.go:12:2: undefined: helper\n")
    assert after - before == set(), "a shifted line number must not read as a new error"


def test_a_genuinely_new_error_is_seen():
    before = _error_keys("store/store.go:41:2: undefined: helper\n")
    after = _error_keys(
        "store/store.go:41:2: undefined: helper\n"
        "store/memory.go:7:6: undefined: sync\n"
    )
    assert after - before == {("store/memory.go", "undefined: sync")}


def test_a_different_message_in_the_same_file_is_new():
    before = _error_keys("store/store.go:41:2: undefined: helper\n")
    after = _error_keys("store/store.go:41:2: undefined: OtherThing\n")
    assert after - before == {("store/store.go", "undefined: OtherThing")}


def test_package_headers_and_no_test_files_lines_are_not_errors():
    keys = _error_keys(
        "# guildlm.dev/x/internal/store\n"
        "?   \tguildlm.dev/x/cmd/server\t[no test files]\n"
    )
    assert keys == set()


def test_a_failure_without_a_file_line_still_counts():
    before = _error_keys("")
    after = _error_keys("--- FAIL: TestGet\n")
    assert after - before == {("", "--- FAIL: TestGet")}
