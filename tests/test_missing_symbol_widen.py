from src.builder import _widen_missing_symbol_targets


def _written():
    return {
        "internal/models/models.go": (
            "package models\n\ntype Task struct{ ID string }\n"
        ),
        "internal/service/service.go": (
            "package service\n\nimport "
            '"guildlm.dev/workapi/internal/models"\n\n'
            "func f() { _ = models.Event{} }\n"
        ),
        "internal/service/service_test.go": "package service\n",
    }


def test_widens_to_owner_package_when_symbol_missing():
    # models.Event is used in service.go but models.go only declares Task —
    # the fix belongs in the models package, not the use site.
    written = _written()
    err = "internal/service/service.go:5:19: undefined: models.Event"
    out = _widen_missing_symbol_targets(["internal/service/service.go"], written, err)
    assert "internal/models/models.go" in out
    # the use site stays targeted; the owner is ADDED, not swapped
    assert "internal/service/service.go" in out
    # test files of the owner are never added
    assert "internal/models/models_test.go" not in out


def test_no_widen_when_symbol_exists():
    # models.Event exists -> the miss is a qualification issue elsewhere, not a
    # missing definition; do not drag models.go in.
    written = _written()
    written["internal/models/models.go"] += "type Event struct{ Type string }\n"
    err = "internal/service/service.go:5:19: undefined: models.Event"
    out = _widen_missing_symbol_targets(["internal/service/service.go"], written, err)
    assert out == ["internal/service/service.go"]


def test_ignores_unknown_package():
    # `undefined: fmt.Nope` — fmt is not a project package; leave it.
    written = _written()
    err = "internal/service/service.go:5:19: undefined: fmt.Nope"
    out = _widen_missing_symbol_targets(["internal/service/service.go"], written, err)
    assert out == ["internal/service/service.go"]
