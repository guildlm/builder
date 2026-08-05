"""The fix loop stops once the error surface has not moved for _STALL_RUN rounds.

WHY THIS IS A RUN AND NOT A REPEAT. The loop already had a guard for a repeated surface, but
it fired only PAST the flat budget and only on set membership. Set membership is the wrong
predicate: `A B A B` repeats at round 3 while the fixer is still moving the build, and stopping
there kills work that may yet converge. An unbroken RUN is the signal that it has stopped
moving. Both cases are pinned below, because the difference is what makes the rule free.

THE THRESHOLD IS MEASURED. Over 133 archived build segments with 2+ reconstructable rounds
(see _repeat_cost.py, which has its own self-test and an out-of-sample split at 25 July):
K=2 destroys one real green, K=3 destroys none and still fires on 61 of 100 never-green
segments. 32 of 33 green segments never repeat a surface consecutively even once.

EVERY TEST HERE IS CONTROLLED: each asserts the round count WITH the guard, and the companion
control asserts the loop runs long WITHOUT it, so a test that passes for the wrong reason is
visible. A guard that never fires and a guard that always fires both look like "green".
"""

import pytest

from src.builder import FileSpec, FileTask, _STALL_RUN, _fix_loop


class _NullCoder:
    """Returns nothing usable, so no repair can succeed and the surface cannot change
    for the right reason. The loop's round count is then purely the guard's doing."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str, temperature: float | None = None) -> str:
        self.calls += 1
        return ""


class _Checker:
    """A check() that replays a fixed sequence of outputs, one per call, then repeats the
    last one forever. Counting calls counts rounds."""

    def __init__(self, *outputs: str) -> None:
        self.outputs = list(outputs)
        self.calls = 0

    def __call__(self, out):
        i = min(self.calls, len(self.outputs) - 1)
        self.calls += 1
        return False, self.outputs[i]


def _run(monkeypatch, tmp_path, checker, stall_run=None, max_fix_rounds=4):
    if stall_run is not None:
        monkeypatch.setattr("src.builder._STALL_RUN", stall_run)
    ok = _fix_loop(
        tasks=[],
        written={},
        out=tmp_path,
        toolchain=None,
        coder=_NullCoder(),
        max_fix_rounds=max_fix_rounds,
        candidates=1,
        check=checker,
    )
    return ok, checker.calls


ERR_A = "# guildlm.dev/x\nx.go:1:1: undefined: Alpha\n"
ERR_B = "# guildlm.dev/x\nx.go:2:2: undefined: Beta\n"
ERR_C = "# guildlm.dev/x\nx.go:3:3: undefined: Gamma\n"

# A real target, so the loop reaches the escalation path at all. With no tasks and no
# written files _fix_targets returns nothing, no file is ever repaired, and the fleet
# handoff — the thing under test — never executes. That silent vacuity is why the
# escalation tests below assert `coder.escalations` before asserting anything else.
_TASKS = [FileTask(index=0, spec=FileSpec(path="x.go", purpose="declares Alpha and Beta"))]
_WRITTEN = {"x.go": "package x\n"}


def test_identical_surface_stops_at_the_threshold(monkeypatch, tmp_path):
    """A B B B B B B: the run reaches 3 at round 4, so the loop performs 4 checks."""
    ok, calls = _run(monkeypatch, tmp_path, _Checker(ERR_A, ERR_B))
    assert ok is False
    assert calls == 4, f"expected to stop on the {_STALL_RUN}rd identical surface, ran {calls}"


def test_control_without_the_guard_runs_to_the_full_budget(monkeypatch, tmp_path):
    """THE CONTROL. Disable the guard (threshold above any reachable run) and the same
    input runs the flat budget. Without this, the test above passes if the loop happens
    to stop early for any unrelated reason."""
    ok, calls = _run(monkeypatch, tmp_path, _Checker(ERR_A, ERR_B), stall_run=99)
    assert ok is False
    assert calls > 4, f"control must run past 4 rounds, ran {calls}"


def test_alternating_surfaces_never_trigger_the_stall_stop(monkeypatch, tmp_path):
    """THE DISCRIMINATOR between a run and a repeat. A B A B A B... repeats from round 3
    under set membership, and must NOT stop here. If this ever equals the count from the
    identical-surface test, the guard has silently become a repeat guard."""
    alt = _Checker(ERR_A, ERR_B, ERR_A, ERR_B, ERR_A, ERR_B, ERR_A, ERR_B)
    ok, calls = _run(monkeypatch, tmp_path, alt)
    assert ok is False
    assert calls > 4, f"alternating surfaces must not trip the run guard, ran {calls}"


def test_a_broken_run_resets_the_counter(monkeypatch, tmp_path):
    """A A B A A ... — two runs of two, never three in a row, so the guard stays silent.
    Pins that the counter RESETS rather than accumulating."""
    ck = _Checker(ERR_A, ERR_A, ERR_B, ERR_A, ERR_A, ERR_B, ERR_A, ERR_A, ERR_B)
    ok, calls = _run(monkeypatch, tmp_path, ck)
    assert ok is False
    assert calls > 4, f"a broken run must not fire the guard, ran {calls}"


def test_progress_is_never_interrupted(monkeypatch, tmp_path):
    """Three genuinely different surfaces in a row: the guard must be invisible. This is
    the false-positive direction — the one that would cost real builds."""
    ck = _Checker(ERR_A, ERR_B, ERR_C)
    ok, calls = _run(monkeypatch, tmp_path, ck)
    assert ok is False
    # C then repeats, so it stops eventually — but only after the three distinct ones.
    assert calls >= 5, f"distinct surfaces must not be cut short, ran {calls}"


class _RejectingToolchain:
    """Every candidate is syntactically unacceptable, so no repair can ever land and the
    surface cannot move for any reason except the guard under test. `check` is injected
    separately, so this only needs the candidate-screening half of the interface."""

    def syntax_ok(self, code: str) -> bool:
        return False


class _EscalatingCoder(_NullCoder):
    """A coder that offers the fleet's escalate() hook and accepts the first N handoffs.

    The point is NOT that escalation repairs anything here — it cannot, since generate()
    still returns nothing. It is that the loop must give the new member its rounds instead
    of stopping on a surface the PREVIOUS member failed to move."""

    def __init__(self, accept: int = 2) -> None:
        super().__init__()
        self.accept = accept
        self.escalations = 0

    def escalate(self, path: str) -> bool:
        if self.escalations >= self.accept:
            return False
        self.escalations += 1
        return True


def test_an_escalation_resets_the_run(monkeypatch, tmp_path):
    """A stalled surface plus a fleet handoff must NOT stop at _STALL_RUN.

    This is the case two existing escalation tests caught and the 133-segment archive sweep
    could not: escalation appears in 1 of 785 archived logs, so 'K=3 kills no green' was
    measured where the fleet was effectively off. The counter means 'same surface, SAME
    fixer' — a handoff changes the fixer.
    """
    coder = _EscalatingCoder(accept=2)
    checker = _Checker(ERR_A, ERR_B)
    monkeypatch.setattr("src.builder._STALL_RUN", 3)
    ok = _fix_loop(
        tasks=_TASKS, written=dict(_WRITTEN), out=tmp_path, toolchain=_RejectingToolchain(),
        coder=coder,
        max_fix_rounds=99, candidates=1, check=checker,
    )
    assert ok is False
    assert coder.escalations, "no handoff happened — this test proves nothing"
    # Without the reset the loop stops at 4 checks regardless of the handoffs.
    assert checker.calls > 4, (
        f"an escalation must buy the new fleet member its rounds; stopped after "
        f"{checker.calls} checks with {coder.escalations} escalation(s)"
    )


def test_the_reset_is_not_unbounded(monkeypatch, tmp_path):
    """Escalations are finite, so the guard must still fire once the fleet is exhausted.
    A reset that never runs out would turn the stall stop off entirely."""
    coder = _EscalatingCoder(accept=1)
    checker = _Checker(ERR_A, ERR_B)
    monkeypatch.setattr("src.builder._STALL_RUN", 3)
    _fix_loop(
        tasks=_TASKS, written=dict(_WRITTEN), out=tmp_path, toolchain=_RejectingToolchain(),
        coder=coder,
        max_fix_rounds=99, candidates=1, check=checker,
    )
    assert checker.calls < 99, f"the guard must still stop the loop, ran {checker.calls}"


@pytest.mark.parametrize("k", [2, 3, 4])
def test_the_threshold_is_the_constant_and_not_a_hardcoded_3(monkeypatch, tmp_path, k):
    """The round count must track _STALL_RUN. A guard hardcoded to 3 passes every test
    above; this is what catches it."""
    ok, calls = _run(monkeypatch, tmp_path, _Checker(ERR_A, ERR_B), stall_run=k, max_fix_rounds=99)
    assert calls == k + 1, f"K={k} should stop after {k + 1} checks, ran {calls}"
