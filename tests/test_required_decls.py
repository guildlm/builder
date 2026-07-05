from src.builder import _is_clean, _required_decls, GoToolchain


def test_required_decls_parses_purpose():
    purpose = (
        "package models. Task struct {ID, Title, Status string} with JSON tags; "
        "Event struct {Type, TaskID string}. An EventEnqueuer INTERFACE { "
        "Enqueue }. Wraps the http.Handler interface."
    )
    req = _required_decls(purpose)
    assert "Task" in req and "Event" in req
    assert "EventEnqueuer" in req  # case-insensitive keyword
    assert "Handler" not in req  # qualified: another package's type


def test_is_clean_rejects_missing_required_type():
    code = "package models\n\ntype Task struct{ ID string }\n"
    tc = GoToolchain()
    assert _is_clean(code, True, tc, required_decls={"Task"})
    assert not _is_clean(code, True, tc, required_decls={"Task", "Event"})
