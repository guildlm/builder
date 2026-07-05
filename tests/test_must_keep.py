from pathlib import Path

from src.builder import GoToolchain, _sample_verified_fix


class StubCoder:
    def __init__(self, responses):
        self._responses = list(responses)

    def generate(self, prompt):
        return self._responses.pop(0) if self._responses else self._responses_last


GO_MOD = "module example.com/m\n\ngo 1.22\n"

MODELS_WITH_EVENT = (
    "package models\n\n"
    "type Task struct{ ID string }\n\n"
    "type Event struct{ Type string }\n"
)
MODELS_WITHOUT_EVENT = "```go\npackage models\n\ntype Task struct{ ID string }\n```"
SERVICE_USES_EVENT = (
    "package service\n\n"
    'import "example.com/m/models"\n\n'
    "func E() models.Event { return models.Event{} }\n"
)


def test_fix_that_deletes_referenced_export_is_rejected(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD)
    (tmp_path / "models").mkdir()
    (tmp_path / "service").mkdir()
    (tmp_path / "models/models.go").write_text(MODELS_WITH_EVENT)
    (tmp_path / "service/service.go").write_text(SERVICE_USES_EVENT)
    written = {
        "models/models.go": MODELS_WITH_EVENT,
        "service/service.go": SERVICE_USES_EVENT,
        "go.mod": GO_MOD,
    }
    coder = StubCoder([MODELS_WITHOUT_EVENT, MODELS_WITHOUT_EVENT])
    code = _sample_verified_fix(
        coder, "fix it", "models/models.go", tmp_path, written, 2,
        GoToolchain(), set(), False, must_keep={"Event"},
    )
    # every candidate deleted Event -> the original file must survive
    assert "type Event" in code
    assert "type Event" in written["models/models.go"]
    assert "type Event" in (tmp_path / "models/models.go").read_text()


def test_fix_that_keeps_referenced_export_is_accepted(tmp_path):
    (tmp_path / "go.mod").write_text(GO_MOD)
    (tmp_path / "models").mkdir()
    (tmp_path / "models/models.go").write_text(MODELS_WITH_EVENT)
    written = {"models/models.go": MODELS_WITH_EVENT, "go.mod": GO_MOD}
    good = (
        "```go\npackage models\n\n"
        "type Task struct{ ID, Title string }\n\n"
        "type Event struct{ Type string }\n```"
    )
    coder = StubCoder([good])
    code = _sample_verified_fix(
        coder, "fix it", "models/models.go", tmp_path, written, 1,
        GoToolchain(), set(), False, must_keep={"Event"},
    )
    assert "Title" in code and "type Event" in code
