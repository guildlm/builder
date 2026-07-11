"""Best-of-N was rejecting every candidate in every multi-package project.

`_is_clean` refuses a candidate that imports anything non-stdlib — the rule that
keeps a small model from reaching for gorilla/mux. But a project's OWN packages
carry a domain too (`guildlm.dev/workapi/internal/store`), so every file of every
multi-package project looked like a foreign dependency. No candidate was ever
clean, best-of-N always fell through to "keep the last sample", and the selection
it exists to perform never happened: 230 fallbacks across the logs, zero
selections.
"""

import shutil

import pytest

from src.builder import GoToolchain, _is_clean, nonstdlib_imports

pytestmark = pytest.mark.skipif(
    shutil.which("go") is None, reason="needs the Go toolchain"
)

MODULE = "guildlm.dev/workapi"

OWN_IMPORTS = """package service

import (
	"context"
	"errors"

	"guildlm.dev/workapi/internal/models"
	"guildlm.dev/workapi/internal/store"
)

type TaskService struct{ store store.Store }

func NewTaskService(s store.Store) *TaskService { return &TaskService{store: s} }

func (s *TaskService) Get(ctx context.Context, id string) (models.Task, error) {
	return models.Task{}, errors.New("x")
}
"""

FOREIGN = """package api

import "github.com/gorilla/mux"

func NewRouter() *mux.Router { return mux.NewRouter() }
"""


def test_a_projects_own_packages_are_not_foreign():
    assert nonstdlib_imports(OWN_IMPORTS, MODULE) == []
    # Without the module it cannot tell, and reports the project's own packages.
    assert nonstdlib_imports(OWN_IMPORTS) == [
        "guildlm.dev/workapi/internal/models",
        "guildlm.dev/workapi/internal/store",
    ]


def test_a_foreign_dependency_is_still_rejected():
    # The rule this check exists for must keep working: a small model reaching
    # for gorilla/mux is still an unclean candidate.
    assert nonstdlib_imports(FOREIGN, MODULE) == ["github.com/gorilla/mux"]
    assert not _is_clean(FOREIGN, True, GoToolchain(), module=MODULE)


def test_a_multi_package_candidate_is_clean_once_the_module_is_known():
    tc = GoToolchain()
    # This is real code from a GREEN artifact — it builds, vets and passes -race.
    assert not _is_clean(OWN_IMPORTS, True, tc)              # the bug
    assert _is_clean(OWN_IMPORTS, True, tc, module=MODULE)   # the fix


def test_the_module_itself_may_be_imported():
    code = f'package main\n\nimport "{MODULE}"\n\nfunc main() {{ _ = {MODULE!r} }}\n'
    assert nonstdlib_imports(code, MODULE) == []
