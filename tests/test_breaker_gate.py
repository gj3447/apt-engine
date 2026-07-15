"""Opt-in circuit-breaker adapter (contrib.breaker_gate) — both directions.

GAP-1: the breaker was an unwired contrib port. ADR-0002 forbids wiring it into the
core (piecemeal promotion), so it is composed via `guarded_measured_gate`. These
tests pin: (a) breaker absent => identical to the core gate (zero behaviour change),
(b) repeated could-not-evaluate ERRORs trip the breaker, (c) while OPEN the gate
short-circuits to a typed fail-closed ERROR without consulting the source, (d) a
HALF_OPEN trial recovers or re-opens, and (e) an evaluated FAIL does NOT trip it.
"""

import json

from apt_engine.contrib.breaker_gate import CIRCUIT_OPEN_REASON, guarded_measured_gate
from apt_engine.contrib.circuit_breaker import CircuitBreaker, InMemoryStore, State
from apt_engine.gate import Verdict, can_advance
from apt_engine.precondition import (
    FileManifestSource,
    ImpactSpec,
    evaluate_measured_mandated_from_with_receipt,
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _breaker(clock):
    return CircuitBreaker(
        InMemoryStore(), "SCW->MetaReview", clock=clock, open_duration_s=30.0, fail_threshold=3
    )


class _EmptyMandatedSource:
    """Healthy source (returns specs, never raises) that mandates nothing -> the gate
    EVALUATES to FAIL (exit 4), an evaluated red rather than an outage. No subprocess."""

    def specs(self):
        return {"SCW->MetaReview": ImpactSpec(("SCW", "MetaReview"), ())}


class _FlakyKgSource:
    """Simulates a KG/manifest backend outage: `specs()` raises the ValueError the
    measured gate folds into a could-not-evaluate ERROR. Counts consultations."""

    def __init__(self) -> None:
        self.calls = 0

    def specs(self):
        self.calls += 1
        raise ValueError("kg bolt down")


class _CountingHealthySource:
    def __init__(self) -> None:
        self.calls = 0

    def specs(self):
        self.calls += 1
        return {"SCW->MetaReview": ImpactSpec(("SCW", "MetaReview"), ())}


# --- (a) breaker absent => identical to the core gate ---------------------- #


def test_breaker_none_is_pass_through_identical():
    src = _EmptyMandatedSource()
    direct, direct_rcpt = evaluate_measured_mandated_from_with_receipt(
        "SCW", "MetaReview", target=".", source=src
    )
    guarded, guarded_rcpt = guarded_measured_gate(
        "SCW", "MetaReview", target=".", source=src, breaker=None
    )
    assert guarded.verdict is direct.verdict is Verdict.FAIL
    assert guarded.reason == direct.reason
    assert guarded_rcpt.gate_kind == direct_rcpt.gate_kind == "measured-mandated"
    assert guarded_rcpt.error is direct_rcpt.error is None


# --- (b) repeated ERROR verdicts trip the breaker -------------------------- #


def test_repeated_error_verdicts_trip_the_breaker():
    breaker = _breaker(FakeClock())
    src = _FlakyKgSource()
    for i in range(3):
        result, _ = guarded_measured_gate("SCW", "MetaReview", target=".", source=src, breaker=breaker)
        assert result.verdict is Verdict.ERROR  # outage folded to could-not-evaluate
        assert src.calls == i + 1  # the source WAS consulted each time (up to the trip)
    # 3 ERRORs == fail_threshold -> OPEN. The 4th call must short-circuit WITHOUT
    # consulting the dead source again.
    assert breaker.check().state is State.OPEN
    result, receipt = guarded_measured_gate("SCW", "MetaReview", target=".", source=src, breaker=breaker)
    assert result.verdict is Verdict.ERROR
    assert src.calls == 3  # NOT consulted while OPEN


# --- (c) OPEN short-circuits to a typed fail-closed ERROR ------------------- #


def test_open_breaker_short_circuits_typed_and_fail_closed():
    breaker = _breaker(FakeClock())
    for _ in range(3):
        breaker.record_failure()  # force OPEN
    src = _CountingHealthySource()
    result, receipt = guarded_measured_gate(
        "SCW", "MetaReview", target=".", source=src, breaker=breaker
    )
    assert result.verdict is Verdict.ERROR
    assert CIRCUIT_OPEN_REASON in result.reason
    assert can_advance(result.verdict) is False  # fail-closed: never advances
    # typed marker on the receipt + never touched the (healthy) source
    assert receipt.verdict == "ERROR"
    assert receipt.error == CIRCUIT_OPEN_REASON
    assert receipt.gate_kind == "measured-mandated"
    assert src.calls == 0
    # the short-circuit receipt is still serialisable / replay-shaped
    assert json.loads(receipt.to_json())["error"] == CIRCUIT_OPEN_REASON


# --- (d) HALF_OPEN trial recovers or re-opens ------------------------------ #


def test_half_open_success_closes_the_breaker(tmp_path):
    clk = FakeClock()
    breaker = _breaker(clk)
    for _ in range(3):
        breaker.record_failure()  # OPEN
    clk.t += 31  # elapse past open_duration -> next check() is a HALF_OPEN trial
    # a real passing mandated test -> PASS -> record_success -> CLOSED
    tf = tmp_path / "test_ok.py"
    tf.write_text("def test_ok():\n    assert True\n")
    man = tmp_path / "m.json"
    man.write_text(json.dumps({"SCW->MetaReview": {"required": ["test_ok.py::test_ok"]}}))
    result, _ = guarded_measured_gate(
        "SCW", "MetaReview", target=str(tmp_path), source=FileManifestSource(str(man)), breaker=breaker
    )
    assert result.verdict is Verdict.PASS
    assert breaker.check().state is State.CLOSED  # trial passed -> closed


def test_half_open_error_reopens_the_breaker():
    clk = FakeClock()
    breaker = _breaker(clk)
    for _ in range(3):
        breaker.record_failure()  # OPEN
    clk.t += 31  # HALF_OPEN trial window
    result, _ = guarded_measured_gate(
        "SCW", "MetaReview", target=".", source=_FlakyKgSource(), breaker=breaker
    )
    assert result.verdict is Verdict.ERROR  # trial hit the outage again
    d = breaker.check()
    assert d.state is State.OPEN and d.allow_request is False  # re-opened, fail-closed


# --- (e) an evaluated FAIL does NOT trip the breaker ----------------------- #


def test_evaluated_fail_does_not_trip_the_breaker():
    breaker = _breaker(FakeClock())
    src = _EmptyMandatedSource()
    for _ in range(5):  # well past fail_threshold=3
        result, _ = guarded_measured_gate("SCW", "MetaReview", target=".", source=src, breaker=breaker)
        assert result.verdict is Verdict.FAIL  # evaluated red, not an outage
    d = breaker.check()
    assert d.state is State.CLOSED and d.allow_request is True  # never tripped
