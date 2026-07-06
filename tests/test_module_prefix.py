from src.builder import _fix_module_prefix


def test_adds_missing_module_domain_prefix():
    # The model wrote local imports without the module's domain prefix
    # ("workapi/..." instead of "guildlm.dev/workapi/...") — go reads them as
    # std-library lookups and fails "is not in std".
    written = {
        "internal/models/models.go": "package models\n",
        "internal/auth/auth.go": "package auth\n",
        "internal/api/router.go": (
            "package api\n\nimport (\n"
            '\t"net/http"\n'
            '\t"workapi/internal/auth"\n'
            ")\n"
        ),
    }
    err = (
        "internal/api/router.go:5:2: package workapi/internal/auth "
        "is not in std (/usr/local/go/src/workapi/internal/auth)"
    )
    out = _fix_module_prefix(written, err, "guildlm.dev/workapi")
    assert "internal/api/router.go" in out
    assert '"guildlm.dev/workapi/internal/auth"' in out["internal/api/router.go"]
    assert '"workapi/internal/auth"' not in out["internal/api/router.go"]
    # untouched imports stay intact
    assert '"net/http"' in out["internal/api/router.go"]


def test_adds_prefix_to_bare_package_basename():
    # The model wrote a bare `import "models"` instead of the full module path.
    written = {
        "internal/models/models.go": "package models\n",
        "internal/store/store.go": (
            'package store\n\nimport (\n\t"context"\n\t"models"\n)\n'
        ),
    }
    err = "internal/store/store.go:5:2: package models is not in std (/x/src/models)"
    out = _fix_module_prefix(written, err, "guildlm.dev/workapi")
    assert '"guildlm.dev/workapi/internal/models"' in out["internal/store/store.go"]
    assert '"context"' in out["internal/store/store.go"]


def test_adds_prefix_to_repo_relative_dir_import():
    written = {
        "internal/models/models.go": "package models\n",
        "internal/store/store.go": 'package store\nimport "internal/models"\n',
    }
    err = "internal/store/store.go:2:8: package internal/models is not in std (x)"
    out = _fix_module_prefix(written, err, "guildlm.dev/workapi")
    assert '"guildlm.dev/workapi/internal/models"' in out["internal/store/store.go"]


def test_ambiguous_basename_is_left_alone():
    # two packages share the basename `models` — don't guess.
    written = {
        "a/models/x.go": "package models\n",
        "b/models/y.go": "package models\n",
        "internal/store/store.go": 'package store\nimport "models"\n',
    }
    err = "internal/store/store.go:2:8: package models is not in std (x)"
    assert _fix_module_prefix(written, err, "guildlm.dev/workapi") == {}


def test_only_rewrites_when_target_is_a_real_project_package():
    # "workapi/internal/nope" has no matching directory in the project — leave it
    # (don't invent a package that doesn't exist).
    written = {
        "internal/api/router.go": (
            'package api\n\nimport "workapi/internal/nope"\n'
        ),
    }
    err = "internal/api/router.go:3:8: package workapi/internal/nope is not in std (x)"
    out = _fix_module_prefix(written, err, "guildlm.dev/workapi")
    assert out == {}


def test_ignores_genuine_stdlib_and_third_party_misses():
    # A path that doesn't start with the module tail is not ours to touch.
    written = {"internal/api/router.go": 'package api\nimport "net/http"\n'}
    err = "internal/api/router.go:2:8: package fmtx is not in std (x)"
    out = _fix_module_prefix(written, err, "guildlm.dev/workapi")
    assert out == {}


def test_noop_without_module():
    written = {"a.go": 'package a\nimport "workapi/internal/x"\n'}
    err = "a.go:2:8: package workapi/internal/x is not in std (x)"
    assert _fix_module_prefix(written, err, None) == {}
    assert _fix_module_prefix(written, err, "singlesegment") == {}

def test_strips_hallucinated_host_prefix_on_full_module_path():
    # The 1.5B hallucinated a "github.com/" host in front of the REAL module
    # path; go reports it as "no required module provides package".
    written = {
        "internal/api/router.go": "package api\n",
        "cmd/server/main.go": (
            "package main\n\nimport (\n"
            '\t"context"\n'
            '\t"github.com/guildlm.dev/taskapi/internal/api"\n'
            ")\n"
        ),
    }
    err = (
        "cmd/server/main.go:5:2: no required module provides package "
        "github.com/guildlm.dev/taskapi/internal/api; to add it:\n"
        "\tgo get github.com/guildlm.dev/taskapi/internal/api"
    )
    out = _fix_module_prefix(written, err, "guildlm.dev/taskapi")
    assert '"guildlm.dev/taskapi/internal/api"' in out["cmd/server/main.go"]
    assert '"github.com/guildlm.dev/taskapi' not in out["cmd/server/main.go"]
    assert '"context"' in out["cmd/server/main.go"]


def test_no_required_module_with_module_tail_form():
    # same error TEXT family, tail-truncated import form
    written = {
        "internal/store/store.go": "package store\n",
        "internal/api/h.go": 'package api\nimport "taskapi/internal/store"\n',
    }
    err = (
        "internal/api/h.go:2:8: no required module provides package "
        "taskapi/internal/store; to add it:"
    )
    out = _fix_module_prefix(written, err, "guildlm.dev/taskapi")
    assert '"guildlm.dev/taskapi/internal/store"' in out["internal/api/h.go"]


def test_no_required_module_third_party_left_alone():
    # a genuine third-party miss (no module path inside) must NOT be rewritten
    written = {
        "internal/api/h.go": 'package api\nimport "github.com/sirupsen/logrus"\n',
    }
    err = (
        "internal/api/h.go:2:8: no required module provides package "
        "github.com/sirupsen/logrus; to add it:"
    )
    assert _fix_module_prefix(written, err, "guildlm.dev/taskapi") == {}
