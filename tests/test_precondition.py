"""Measured-precondition resolver — deterministic exit_code -> verdict, no forgery.

The fix-harness (test_fix_harness_20260627) is the RED frontier ledger; this is
the permanent unit home for the resolver behaviour.
"""

import inspect

from apt_engine.precondition import evaluate_measured, measure


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
