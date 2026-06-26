"""Enforcement-mode mapping — INFORMATIONAL advisory vs BLOCKER fail-closed."""

from apt_engine.gate_policy import EnforcementMode, OutwardVerdict, enforce

BLOCK = EnforcementMode.BLOCKER
INFO = EnforcementMode.INFORMATIONAL


def test_pass_is_pass_in_both_modes_never_advisory():
    for mode in (BLOCK, INFO):
        r = enforce(passed=True, mode=mode)
        assert r.verdict is OutwardVerdict.PASS
        assert r.advisory_only is False


def test_blocker_failure_blocks():
    r = enforce(passed=False, mode=BLOCK)
    assert r.verdict is OutwardVerdict.FAIL
    assert r.advisory_only is False


def test_informational_failure_is_advisory_would_fail():
    r = enforce(passed=False, mode=INFO)
    assert r.verdict is OutwardVerdict.WOULD_FAIL
    assert r.advisory_only is True


def test_circuit_open_blocker_is_open_refused():
    r = enforce(passed=True, mode=BLOCK, circuit_open=True)
    assert r.verdict is OutwardVerdict.OPEN_REFUSED


def test_circuit_open_informational_is_advisory():
    r = enforce(passed=True, mode=INFO, circuit_open=True)
    assert r.verdict is OutwardVerdict.WOULD_FAIL
    assert r.advisory_only is True
