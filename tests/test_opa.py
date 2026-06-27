"""OPA policy evaluation — StaticOPAPolicy is fail-closed and testable sans server."""

from apt_engine.opa import OPADecision, OPAPolicy, StaticOPAPolicy


def test_static_policy_allow_and_deny():
    pol = StaticOPAPolicy(
        {
            "apt/phase_gates/sa_to_sp/allow": lambda inp: inp.get("anchor_complete", False),
        }
    )
    assert pol.evaluate("apt/phase_gates/sa_to_sp/allow", {"anchor_complete": True}).allow is True
    assert pol.evaluate("apt/phase_gates/sa_to_sp/allow", {"anchor_complete": False}).allow is False


def test_unknown_policy_is_default_deny():
    pol = StaticOPAPolicy({})
    d = pol.evaluate("apt/unknown", {})
    assert d.allow is False  # fail-closed
    assert "default" in d.reason


def test_default_allow_override():
    pol = StaticOPAPolicy({}, default_allow=True)
    assert pol.evaluate("apt/unknown", {}).allow is True


def test_boolean_rule():
    pol = StaticOPAPolicy({"p": True})
    assert pol.evaluate("p", {}).allow is True


def test_static_policy_satisfies_protocol():
    assert isinstance(StaticOPAPolicy(), OPAPolicy)
    assert isinstance(OPADecision(True, "x"), OPADecision)
