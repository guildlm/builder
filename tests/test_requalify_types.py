from src.builder import _requalify_undefined

# The workapi frontier residual: a package `service` test uses sibling-package
# symbols in BOTH type position (Event, Task) and call position (NewMemStore)
# while importing only its own package. The call was already requalified before;
# the type positions were the surviving `undefined:` errors that stalled workapi.
MODULE = "guildlm.dev/workapi"

_WRITTEN = {
    "internal/models/models.go": (
        "package models\n\n"
        "type Task struct{ ID, Title, Status string }\n"
        "type Event struct{ Type, TaskID string }\n"
    ),
    "internal/store/store.go": (
        "package store\n\n"
        'import "guildlm.dev/workapi/internal/models"\n\n'
        "type MemStore struct{ m map[string]models.Task }\n"
        "func NewMemStore() *MemStore { return &MemStore{m: map[string]models.Task{}} }\n"
    ),
    "internal/service/service.go": (
        "package service\n\n"
        'import "guildlm.dev/workapi/internal/models"\n\n'
        "type EventEnqueuer interface{ Enqueue(models.Event) }\n"
        "func NewTaskService(s any, e EventEnqueuer) *taskService { return &taskService{} }\n"
        "type taskService struct{}\n"
    ),
    "internal/service/service_test.go": (
        "package service\n\n"
        'import "testing"\n\n'
        "type fakeEnqueuer struct{ Events []Event }\n\n"
        "func (f *fakeEnqueuer) Enqueue(e Event) { f.Events = append(f.Events, e) }\n\n"
        "func TestCreate(t *testing.T) {\n"
        "\tfake := &fakeEnqueuer{}\n"
        "\tsvc := NewTaskService(NewMemStore(), fake)\n"
        "\ttask := Task{ID: \"1\"}\n"
        "\t_ = svc\n"
        "\t_ = task\n"
        "\t_ = len(fake.Events)\n"
        "}\n"
    ),
}


def test_requalifies_type_positions_and_calls_together():
    err = (
        "internal/service/service_test.go:5:33: undefined: Event\n"
        "internal/service/service_test.go:10:29: undefined: NewMemStore\n"
        "internal/service/service_test.go:11:14: undefined: Task\n"
    )
    out = _requalify_undefined(_WRITTEN, err, MODULE)
    fixed = out["internal/service/service_test.go"]
    # type positions now qualified
    assert "Events []models.Event" in fixed
    assert "Enqueue(e models.Event)" in fixed
    assert "task := models.Task{" in fixed
    # call still qualified
    assert "store.NewMemStore()" in fixed
    # the imports for both owning packages were added
    assert '"guildlm.dev/workapi/internal/models"' in fixed
    assert '"guildlm.dev/workapi/internal/store"' in fixed
    # a field-access (.Events) and the field name (Events) are NOT mangled
    assert "fake.Events" in fixed
    assert "struct{ Events []models.Event }" in fixed or "Events []models.Event" in fixed


def test_does_not_touch_package_qualified_use():
    # `undefined: models` (a package used qualified but not imported) is an
    # import-only fix, never a rewrite of models.X occurrences.
    written = {
        "internal/api/h.go": (
            "package api\n\n"
            "func f() { _ = models.Task{} }\n"
        ),
        "internal/models/models.go": (
            "package models\n\ntype Task struct{ ID string }\n"
        ),
    }
    err = "internal/api/h.go:3:15: undefined: models\n"
    out = _requalify_undefined(written, err, MODULE)
    fixed = out["internal/api/h.go"]
    assert '"guildlm.dev/workapi/internal/models"' in fixed
    # models.Task stays exactly once — not turned into models.models.Task
    assert "models.models" not in fixed


def test_ambiguous_owner_left_alone():
    # a symbol exported by TWO packages is ambiguous — do not guess.
    written = {
        "internal/a/a.go": "package a\n\ntype Widget struct{}\n",
        "internal/b/b.go": "package b\n\ntype Widget struct{}\n",
        "internal/c/c.go": "package c\n\nfunc f() { _ = Widget{} }\n",
    }
    err = "internal/c/c.go:3:16: undefined: Widget\n"
    assert _requalify_undefined(written, err, MODULE) == {}
