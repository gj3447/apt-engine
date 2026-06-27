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


def test_importing_core_does_not_load_contrib():
    # Stronger than grepping one module (red-team LOW-6): in a FRESH interpreter,
    # `import apt_engine` must not transitively pull in any apt_engine.contrib.*.
    import os
    import subprocess
    import sys

    probe = (
        "import sys, apt_engine; "
        "leaked = [m for m in sys.modules if m.startswith('apt_engine.contrib')]; "
        "print(','.join(leaked)); "
        "sys.exit(1 if leaked else 0)"
    )
    r = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, env=os.environ.copy(),
    )
    assert r.returncode == 0, f"`import apt_engine` pulled in contrib: {r.stdout.strip()}"
