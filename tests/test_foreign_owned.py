from src.builder import FileSpec, _foreign_owned_decls


FILES = [
    FileSpec(path="internal/models/models.go", purpose=(
        "package models. Task struct {ID, Title, Status string}; "
        "Event struct {Type, TaskID string}."
    )),
    FileSpec(path="internal/store/memory.go", purpose=(
        "package store. Goroutine-safe MemStore struct over models.Task."
    )),
    FileSpec(path="internal/store/store.go", purpose=(
        "package store. Store interface {Create/Get/List/Delete}."
    )),
]


def test_store_file_cannot_own_models_types():
    owned = _foreign_owned_decls(FILES, "internal/store/memory.go",
                                 FILES[1].purpose)
    assert "Task" in owned and "Event" in owned  # models.go owns these
    assert "MemStore" not in owned  # own purpose's type stays declarable
    assert "Store" not in owned  # same-dir sibling is not foreign


def test_models_file_keeps_its_own_types():
    owned = _foreign_owned_decls(FILES, "internal/models/models.go",
                                 FILES[0].purpose)
    assert "Task" not in owned and "Event" not in owned
    assert "MemStore" in owned  # the store's type is foreign to models
