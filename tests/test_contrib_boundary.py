"""ADR-0002 boundary pin — the layer-2 ports stay OUT of the core surface.

The deep-think's T2 was that `apt_engine.__all__` advertised unwired ports. This
locks the CUT: the belt is importable only from `apt_engine.contrib`, never from
the core public surface, and is not wired into `evaluate_transition`.
"""

import apt_engine


_BELT = {
    "enforce", "EnforcementMode", "OutwardVerdict",
    "CircuitBreaker", "InMemoryStore", "State",
    "GateOverride", "make_override", "override_allows", "disclosure",
    "OPADecision", "OPAPolicy", "StaticOPAPolicy", "HTTPOPAClient",
}


def test_belt_is_not_in_core_public_surface():
    leaked = _BELT & set(apt_engine.__all__)
    assert not leaked, f"layer-2 ports leaked back into apt_engine.__all__: {leaked}"


def test_belt_is_importable_from_contrib():
    from apt_engine.contrib import (  # noqa: F401
        CircuitBreaker,
        GateOverride,
        StaticOPAPolicy,
        enforce,
    )
    from apt_engine.contrib.resolver import check_drift  # noqa: F401


def test_core_module_does_not_import_the_belt():
    # The deterministic core must not depend on the ports (no composition root).
    import apt_engine.gate as gate

    src = gate.evaluate_transition.__module__
    assert src == "apt_engine.gate"
    # gate.py imports only phases — never contrib.
    import inspect

    text = inspect.getsource(gate)
    for name in ("contrib", "circuit_breaker", "opa", "gate_policy", "gate_override"):
        assert name not in text, f"core gate.py references a layer-2 port: {name}"
