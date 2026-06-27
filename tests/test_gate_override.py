"""GateOverride — ADR-grounded escape-hatch invariants (revert-proof)."""

from datetime import datetime, timedelta

import pytest

from apt_engine.gate import Verdict, evaluate_transition
from apt_engine.contrib.gate_override import (
    PERMANENT_PHRASE,
    disclosure,
    make_override,
    override_allows,
)

NOW = datetime(2026, 6, 26, 12, 0, 0)


def _fail_result():
    # ST -> SCW with unmet precondition is a canonical FAIL.
    r = evaluate_transition("ST", "SCW", precondition_met=False)
    assert r.verdict is Verdict.FAIL
    return r


def _ov(**kw):
    base = dict(
        cycle_id="cyc-1", phase="SCW", bypass_reason="hotfix release window",
        authorized_by="user: proceed", created_at=NOW,
    )
    base.update(kw)
    return make_override(**base)


def test_no_silent_override_requires_reason_and_authorization():
    with pytest.raises(ValueError):
        _ov(bypass_reason="   ")
    with pytest.raises(ValueError):
        _ov(authorized_by="")


def test_default_ttl_is_24h():
    ov = _ov()
    assert ov.expires_at == NOW + timedelta(hours=24)
    assert ov.active(NOW) is True
    assert ov.active(NOW + timedelta(hours=23, minutes=59)) is True
    assert ov.active(NOW + timedelta(hours=24)) is False  # half-open: expiry excluded


def test_expired_override_does_not_allow():
    ov = _ov()
    later = NOW + timedelta(hours=25)
    assert override_allows(_fail_result(), ov, later) is False


def test_permanent_requires_the_phrase():
    with pytest.raises(ValueError):
        _ov(permanent=True)  # authorized_by lacks the phrase
    ov = _ov(permanent=True, authorized_by=f"user: {PERMANENT_PHRASE} approved")
    assert ov.permanent is True
    assert ov.active(datetime(3000, 1, 1)) is True


def test_override_only_applies_to_fail():
    # Phase is matched on purpose so ONLY the FAIL guard can reject — otherwise a
    # phase mismatch would mask the verdict guard and the test would pass for the
    # wrong reason (adversarial self-check: keep this guard isolated/revert-proof).
    a_pass = evaluate_transition("SA", "SP", precondition_met=True)
    assert a_pass.verdict is Verdict.PASS
    assert override_allows(a_pass, _ov(phase="SP"), NOW) is False
    skip = evaluate_transition("SP", "ST", precondition_met=True, skipped=True)
    assert skip.verdict is Verdict.SKIP
    assert override_allows(skip, _ov(phase="ST"), NOW) is False
    cond = evaluate_transition("SCW", "MetaReview", precondition_met=True, conditional=True)
    assert cond.verdict is Verdict.CONDITIONAL
    assert override_allows(cond, _ov(phase="MetaReview"), NOW) is False


def test_override_phase_must_match_gate_destination():
    ov = _ov(phase="MetaReview")  # wrong phase for an ST->SCW gate
    assert override_allows(_fail_result(), ov, NOW) is False


def test_active_override_allows_failed_gate():
    assert override_allows(_fail_result(), _ov(), NOW) is True


def test_disclosure_is_never_silent():
    msg = disclosure(_fail_result(), _ov())
    assert "GATE OVERRIDE" in msg
    assert "OVERRIDE_DELEGATED" in msg
    assert "cyc-1" in msg and "v27_phase_scw_dispatch_guard" in msg
