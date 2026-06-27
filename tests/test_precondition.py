"""Measured-precondition resolver — deterministic exit_code -> verdict, no forgery.

The fix-harness (test_fix_harness_20260627) is the RED frontier ledger; this is
the permanent unit home for the resolver behaviour.
"""

import inspect

import pytest

from apt_engine.precondition import evaluate_measured, evaluate_measured_default, measure


def test_measure_reads_truth_off_exit_code():
    assert measure(lambda t: 0, "impact").met is True
    assert measure(lambda t: 1, "impact").met is False
    assert measure(lambda t: 5, "impact").exit_code == 5
    assert measure(lambda t: 0, "impact").source == "pytest:impact"


def test_pytest_pass_unlocks_scw_to_metareview():
    r = evaluate_measured("SCW", "MetaReview", runner=lambda t: 0, target="impact")
    assert r.verdict.value == "PASS"


def test_pytest_fail_blocks_with_canonical_gate_version():
    r = evaluate_measured("SCW", "MetaReview", runner=lambda t: 1, target="impact")
    assert r.verdict.value == "FAIL"
    assert r.gate_version == "v27_phase_meta_review_dispatch_guard"


def test_truth_is_unforgeable_no_caller_bool():
    # The whole point: no caller-supplied bool can override the measurement.
    assert "precondition_met" not in inspect.signature(evaluate_measured).parameters


def test_measurement_cannot_bypass_structural_adjacency():
    # A measured PASS still cannot force a non-adjacent transition (SCW->Cleanup):
    # measurement composes WITH the by-construction invariants, it does not defeat them.
    r = evaluate_measured("SCW", "Cleanup", runner=lambda t: 0, target="impact")
    assert r.verdict.value == "FAIL"
    assert "non-adjacent" in r.reason


def test_only_exit_zero_is_met():
    # M-B: only exit 0 is met. collection-error(2), no-tests-collected(5), etc.
    # must all be UNMET, so a non-{0,1} regression can't pass as fake-green.
    assert measure(lambda t: 0, "impact").met is True
    for code in (1, 2, 3, 4, 5):
        assert measure(lambda t: code, "impact").met is False, f"exit {code} must be unmet"


def test_evaluate_measured_has_no_kwargs_passthrough_and_fixed_params():
    # M-A: the anti-fake-green property must be a PROPERTY, not a single spelling.
    # No **kwargs -> a future second override (e.g. assume_met) is a hard TypeError,
    # and the exact param whitelist trips if anyone widens the surface.
    assert set(inspect.signature(evaluate_measured).parameters) == {
        "from_phase", "to_phase", "runner", "target", "conditional", "skipped",
    }
    with pytest.raises(TypeError):
        evaluate_measured("SCW", "MetaReview", runner=lambda t: 1, target="x", assume_met=True)


def test_default_variant_exposes_no_injectable_runner():
    # H-C / M-A: the production entry hardwires pytest_runner; a caller cannot
    # forge the exit code by injecting a runner.
    assert set(inspect.signature(evaluate_measured_default).parameters) == {
        "from_phase", "to_phase", "target", "conditional", "skipped",
    }
    with pytest.raises(TypeError):
        evaluate_measured_default("SCW", "MetaReview", runner=lambda t: 0, target="x")


def test_default_variant_maps_real_runner_exit_code(monkeypatch):
    import apt_engine.precondition as pre

    monkeypatch.setattr(pre, "pytest_runner", lambda target: 1)
    assert evaluate_measured_default("SCW", "MetaReview", target="impact").verdict.value == "FAIL"
    monkeypatch.setattr(pre, "pytest_runner", lambda target: 0)
    assert evaluate_measured_default("SCW", "MetaReview", target="impact").verdict.value == "PASS"
