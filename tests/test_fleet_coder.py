"""FleetCoder: per-file escalation across a model fleet.

The ensemble evidence (guild-code go/crucible/ROUTING-DESIGN.md) says no single model
beats the base but a {base, final, 14b} fleet solves what the base misses. FleetCoder is
the mechanism: base first, and a file that keeps failing the gate escalates to the next
member. These tests pin that behaviour with FakeCoders (no live model), and — critically —
that a one-member fleet is indistinguishable from that lone coder, so wiring it in cannot
regress an unrouted build.
"""
import pytest

from src.builder import FakeCoder, FleetCoder, RoleRoutingCoder, _parse_fleet


def _prompt(path):
    return f"TARGET_FILE: {path}\nwrite the file"


def test_generates_from_the_first_member_by_default():
    fleet = FleetCoder([FakeCoder({"a.go": ["base"]}), FakeCoder({"a.go": ["spec"]})])
    assert fleet.generate(_prompt("a.go")) == "base"
    assert fleet.member_for("a.go") == 0


def test_escalate_advances_that_file_to_the_next_member():
    fleet = FleetCoder([FakeCoder({"a.go": ["base"]}), FakeCoder({"a.go": ["spec"]})])
    assert fleet.escalate("a.go") is True
    assert fleet.member_for("a.go") == 1
    assert fleet.generate(_prompt("a.go")) == "spec"


def test_escalation_is_per_file_independent():
    fleet = FleetCoder([
        FakeCoder({"a.go": ["a0"], "b.go": ["b0"]}),
        FakeCoder({"a.go": ["a1"], "b.go": ["b1"]}),
    ])
    fleet.escalate("a.go")
    # a.go advanced; b.go untouched
    assert fleet.generate(_prompt("a.go")) == "a1"
    assert fleet.generate(_prompt("b.go")) == "b0"
    assert fleet.member_for("b.go") == 0


def test_escalate_returns_false_on_the_last_member():
    fleet = FleetCoder([FakeCoder({"a.go": ["x"]}), FakeCoder({"a.go": ["y"]})])
    assert fleet.escalate("a.go") is True
    assert fleet.escalate("a.go") is False  # no third member — caller should stop
    assert fleet.member_for("a.go") == 1  # stays put


def test_three_member_fleet_walks_base_then_final_then_14b():
    fleet = FleetCoder([
        FakeCoder({"a.go": ["base"]}),
        FakeCoder({"a.go": ["final"]}),
        FakeCoder({"a.go": ["14b"]}),
    ])
    seen = [fleet.generate(_prompt("a.go"))]
    while fleet.escalate("a.go"):
        seen.append(fleet.generate(_prompt("a.go")))
    assert seen == ["base", "final", "14b"]


def test_single_member_fleet_is_backward_compatible():
    """One member => never escalates, behaves exactly like that coder. This is what
    makes wiring FleetCoder into the fix loop a no-op for an unrouted (single-model) build."""
    lone = FakeCoder({"a.go": ["only"]})
    fleet = FleetCoder([lone])
    assert fleet.generate(_prompt("a.go")) == "only"
    assert fleet.escalate("a.go") is False
    assert fleet.member_for("a.go") == 0


def test_empty_fleet_rejected():
    with pytest.raises(ValueError):
        FleetCoder([])


def test_role_routing_forwards_escalation_to_the_owning_role_fleet():
    """A dev fleet + a single test specialist: escalating a dev file advances the dev
    fleet; escalating a test file (owned by a non-fleet coder) is a no-op. This is what
    lets fleet routing compose with the existing role routing."""
    dev_fleet = FleetCoder([
        FakeCoder({"impl.go": ["base"]}),
        FakeCoder({"impl.go": ["spec"]}),
    ])
    test_coder = FakeCoder({"impl_test.go": ["t"]})
    router = RoleRoutingCoder({"dev": dev_fleet, "test": test_coder})

    # dev file -> forwarded to the dev fleet, which advances
    assert router.escalate("impl.go") is True
    assert dev_fleet.member_for("impl.go") == 1
    assert router.generate("TARGET_FILE: impl.go") == "spec"

    # test file -> owning coder is not a fleet, so escalation is a no-op
    assert router.escalate("impl_test.go") is False


@pytest.mark.parametrize("spec, expected", [
    (None, []),
    ("", []),
    ("   ", []),
    ("go-dev-final", [("go-dev-final", None)]),
    ("go-dev-final,go-dev-14b", [("go-dev-final", None), ("go-dev-14b", None)]),
    ("go-dev-14b@http://localhost:8081/v1",
     [("go-dev-14b", "http://localhost:8081/v1")]),
    (" go-dev-final , go-dev-14b@u ", [("go-dev-final", None), ("go-dev-14b", "u")]),
    ("a,,b", [("a", None), ("b", None)]),  # blank members skipped
])
def test_parse_fleet(spec, expected):
    assert _parse_fleet(spec) == expected
