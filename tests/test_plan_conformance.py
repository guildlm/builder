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


# --------------------------------------------------------------------------- #
# The parity clause, and the switch that withholds it.
#
# The completeness rule tells a file to make every method "EXIST ON BOTH the
# interface and its implementation" — including a file whose purpose reads "The
# Store INTERFACE only — no implementation in this file". The switch withholds
# that one sentence from that one kind of file.
#
# These tests exist because the last two rules I added this session each had a
# silent-no-op failure mode that measured CLEAN: the disclaimer rule matched
# nothing at all on its first implementation, and a looser interface-only
# predicate would have fired only on test files, where the rule is never emitted.
# A switch that drives an experiment and quietly does nothing is worse than no
# switch, because the experiment still returns a number.
# --------------------------------------------------------------------------- #

import os  # noqa: E402

from src.builder import _INTERFACE_ONLY_RE, _generate_prompt, plan  # noqa: E402

INTERFACE_ONLY = "package store. The Store INTERFACE only — no implementation in this file."
IMPL = "package store. `MemStore` — the in-memory implementation of the Store interface."

PARITY_SPEC = Spec(
    name="parity", description="d", go_module="guildlm.dev/parity",
    files=(
        FileSpec(path="store/store.go", purpose=INTERFACE_ONLY),
        FileSpec(path="store/memory.go", purpose=IMPL),
    ),
)

PARITY = "INTERFACE/IMPL PARITY"
LANE = "STAY IN YOUR LANE"
EVERY = "IMPLEMENT EVERY"


def _prompt_for(path, rules):
    tasks = plan(PARITY_SPEC)
    task = [t for t in tasks if t.spec.path == path][0]
    written = {t.spec.path: "package store\n" for t in tasks if t.index < task.index}
    old = os.environ.get("GUILDLM_ENABLE_RULES", "")
    os.environ["GUILDLM_ENABLE_RULES"] = rules
    try:
        return _generate_prompt(PARITY_SPEC, task, written)
    finally:
        os.environ["GUILDLM_ENABLE_RULES"] = old


def test_off_by_default_so_todays_wording_is_the_control_arm():
    p = _prompt_for("store/store.go", "")
    assert PARITY in p and LANE in p and EVERY in p


def test_the_switch_withholds_the_clause_from_the_interface_only_file():
    p = _prompt_for("store/store.go", "interface_only_scope")
    assert PARITY not in p
    # and takes nothing else with it — the arm must differ by ONE sentence
    assert LANE in p and EVERY in p


def test_the_implementer_keeps_the_clause_under_the_same_flag():
    p = _prompt_for("store/memory.go", "interface_only_scope")
    assert PARITY in p, "only the file forbidden to implement may lose it"


def test_an_unrelated_rule_name_does_not_trip_the_switch():
    assert PARITY in _prompt_for("store/store.go", "completeness,mutex_intra")


def test_the_predicate_ignores_no_possible_implementation_prose():
    # ratelimit and taskapipro TEST purposes say "no implementation can make that
    # pass" — no POSSIBLE implementation, not "none in this file". A loose
    # predicate matches them, and because the rule is never emitted for test
    # files it would have measured perfectly clean.
    assert not _INTERFACE_ONLY_RE.search(
        "the two expectations contradict each other and no implementation can satisfy both"
    )
    assert not _INTERFACE_ONLY_RE.search(
        "the next one sees 429 where it expects 200, and no implementation can make that pass"
    )
    assert _INTERFACE_ONLY_RE.search(INTERFACE_ONLY)


# --------------------------------------------------------------------------- #
# Goroutine dumps are not errors, and their NUMBERS change every run.
#
# Measured on the corpus: four of five gate refusals were this and nothing else —
# a panicking test printed a dump, the goroutine ids differed between the before
# and after runs, every dump line keyed as a brand-new error, and the gate
# refused a move that changed nothing. The direction was conservative, so it cost
# recall rather than safety, but "52 of 59" was partly a measure of which trees
# have panicking tests.
# --------------------------------------------------------------------------- #

GORO_BEFORE = """--- FAIL: TestGet (0.00s)
panic: assignment to entry in nil map [recovered]
goroutine 22 [running]:
	testing.tRunner.func1.2({0x104c1a0, 0x1053e70})
	/opt/homebrew/Cellar/go/1.25.3/libexec/src/testing/testing.go:1734 +0x1bc
created by testing.(*T).Run in goroutine 20
"""

GORO_AFTER = GORO_BEFORE.replace("goroutine 22", "goroutine 36").replace(
    "goroutine 20", "goroutine 34"
)


def test_a_goroutine_dump_with_different_ids_is_not_a_new_error():
    assert _error_keys(GORO_AFTER) - _error_keys(GORO_BEFORE) == set()


def test_the_panic_itself_is_still_an_error():
    keys = _error_keys(GORO_BEFORE)
    assert ("", "panic: assignment to entry in nil map [recovered]") in keys
    assert ("", "--- FAIL: TestGet") in keys


def test_a_new_panic_is_still_seen_through_the_dump():
    after = GORO_AFTER.replace(
        "panic: assignment to entry in nil map", "panic: index out of range"
    )
    assert _error_keys(after) - _error_keys(GORO_BEFORE) == {
        ("", "panic: index out of range [recovered]")
    }


def test_the_real_refusal_from_the_corpus_still_refuses():
    # workapi2: the ONE genuine refusal in the whole run — the move left an
    # import the module cannot resolve. It must survive the noise filter.
    before = _error_keys("")
    after = _error_keys(
        "internal/store/memory.go: package models is not in std "
        "(/opt/homebrew/Cellar/go/1.25.3/libexec/src/models)\n"
    )
    assert len(after - before) == 1


# --------------------------------------------------------------------------- #
# ...and the repair itself now runs on a failing build too.
#
# It used to stay behind the green gate, on the reasoning that a move on a broken
# tree cannot pass toolchain.check and reverts anyway. True of the old gate;
# false by measurement once the gate became non-regressing — 52 of 59 red-tree
# cases carried a correct move that was being discarded on evidence about errors
# the move neither caused nor could fix.
#
# The fixture above keeps the NO-DONOR shape (store.go's purpose also promises
# MemStore, so the ownership rule correctly refuses to take it) and therefore
# still warns. This one gives the donor no claim on the symbol, so the move is
# legitimate — on a project that does not compile.
# --------------------------------------------------------------------------- #

DONOR_SPEC = Spec(
    name="conf2", description="d", go_module="guildlm.dev/conf",
    files=(
        FileSpec(path="go.mod", purpose="MARK_GOMOD. The module file."),
        FileSpec(
            path="internal/store/store.go",
            # promises the interface ONLY — so MemStore is not its to keep
            purpose="MARK_STORE. package store. The Store INTERFACE only.",
        ),
        FileSpec(
            path="internal/store/memory.go",
            purpose="MARK_MEMORY. package store. Implements the `MemStore` type.",
        ),
        FileSpec(
            path="cmd/server/main.go",
            purpose="MARK_MAIN. package main with func main, wiring the store.",
        ),
        FileSpec(
            path="internal/bad/bad.go",
            purpose="MARK_BAD. package bad. A helper.",
        ),
    ),
)


# The store package must COMPILE here, and the build must fail somewhere else.
# The first version of this fixture reused CONF_STORE, whose MemStore.Get calls an
# undefined helper — and the move was refused, because the error TRAVELS WITH the
# declarations and (file, message) reads it as new in its new home. That is a real
# limitation of the comparison key, recorded separately; it is not what this test
# is about, and entangling the two would have tested neither.
CLEAN_STORE = """package store

type Store interface {
	Get(id string) (string, error)
}

type MemStore struct{ items map[string]string }

func NewMemStore() *MemStore { return &MemStore{items: map[string]string{}} }

func (m *MemStore) Get(id string) (string, error) { return m.items[id], nil }
"""


class CleanStoreCoder(ScriptedCoder):
    """store compiles; a DIFFERENT package does not, so the build cannot converge
    and the failure has nothing to do with the declarations being moved."""

    def generate(self, prompt: str, temperature: float | None = None) -> str:
        if "MARK_STORE" in prompt:
            return CLEAN_STORE
        if "MARK_BAD" in prompt:
            return "package bad\n\nfunc F() { undefinedCall() }\n"
        return super().generate(prompt, temperature)


def test_the_repair_runs_on_a_build_that_never_goes_green(tmp_path, capsys):
    from src.builder import build

    ok, written = build(
        DONOR_SPEC, CleanStoreCoder(), tmp_path, max_fix_rounds=1,
        toolchain=GoToolchain(),
    )

    assert not ok, "the fixture is only meaningful if the build FAILS"
    # the declaration the plan gave memory.go is now IN memory.go, on a red tree
    assert "internal/store/memory.go" not in empty_go_files(written)
    assert "MemStore" in written["internal/store/memory.go"]
    assert "type MemStore struct" not in written["internal/store/store.go"]
    # and store.go keeps its own job
    assert "type Store interface" in written["internal/store/store.go"]

    err = capsys.readouterr().err
    assert "moved MemStore" in err
    assert "project still failing, but not for this" in err, (
        "the log must say the project is still red, or a reader will take the "
        "move for a fix:\n" + err
    )


# --------------------------------------------------------------------------- #
# The gate counts MESSAGES, and drops the file — because errors travel.
#
# A move relocates declarations, and any error inside them moves with the code.
# workapi2's store.go holds a bare `import "models"` that already fails; after
# the move the identical defect is reported against memory.go. Keyed by
# (file, message) that reads as new, and it was the only thing still refusing
# anything in the corpus — a move punished for damage it did not do.
#
# Counting keeps what the file used to cover: a SECOND instance of an existing
# message raises the count and is still refused.
# --------------------------------------------------------------------------- #

from src.builder import _error_counts  # noqa: E402


def test_an_error_that_changes_file_is_not_new():
    before = _error_counts("internal/store/store.go:6:2: package models is not in std\n")
    after = _error_counts("internal/store/memory.go:4:2: package models is not in std\n")
    assert not {m for m, n in after.items() if n > before.get(m, 0)}


def test_a_second_instance_of_the_same_message_IS_new():
    before = _error_counts("a.go:1:1: undefined: X\n")
    after = _error_counts("a.go:1:1: undefined: X\nb.go:9:2: undefined: X\n")
    assert {m for m, n in after.items() if n > before.get(m, 0)} == {"undefined: X"}


def test_a_brand_new_message_is_still_new():
    before = _error_counts("a.go:1:1: undefined: X\n")
    after = _error_counts("a.go:1:1: undefined: X\na.go:2:2: undefined: Y\n")
    assert {m for m, n in after.items() if n > before.get(m, 0)} == {"undefined: Y"}


def test_go_repeating_one_error_per_package_does_not_read_as_growth():
    # go prints the same failure once per dependent package; that repetition is
    # stable across a relocation (verified on workapi2) and must not itself
    # register as an increase when the text is identical.
    text = "a.go:1:1: undefined: X\n" * 5
    before, after = _error_counts(text), _error_counts(text)
    assert not {m for m, n in after.items() if n > before.get(m, 0)}
