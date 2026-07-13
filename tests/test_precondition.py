"""Measured-precondition resolver — deterministic exit_code -> verdict, no forgery.

The fix-harness (test_fix_harness_20260627) is the RED frontier ledger; this is
the permanent unit home for the resolver behaviour.
"""

import inspect
import sys
from types import SimpleNamespace

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
        "from_phase",
        "to_phase",
        "runner",
        "target",
        "conditional",
        "skipped",
    }
    with pytest.raises(TypeError):
        evaluate_measured("SCW", "MetaReview", runner=lambda t: 1, target="x", assume_met=True)


def test_default_variant_exposes_no_injectable_runner():
    # H-C / M-A: the production entry hardwires pytest_runner; a caller cannot
    # forge the exit code by injecting a runner.
    assert set(inspect.signature(evaluate_measured_default).parameters) == {
        "from_phase",
        "to_phase",
        "target",
        "conditional",
        "skipped",
    }
    with pytest.raises(TypeError):
        evaluate_measured_default("SCW", "MetaReview", runner=lambda t: 0, target="x")


def test_default_variant_maps_real_runner_exit_code(monkeypatch):
    import apt_engine.precondition as pre

    monkeypatch.setattr(pre, "pytest_runner", lambda target: 1)
    assert evaluate_measured_default("SCW", "MetaReview", target="impact").verdict.value == "FAIL"
    monkeypatch.setattr(pre, "pytest_runner", lambda target: 0)
    assert evaluate_measured_default("SCW", "MetaReview", target="impact").verdict.value == "PASS"


def test_all_production_pytest_subprocesses_use_python_isolated_mode(monkeypatch, tmp_path):
    """Pin `python -I -m pytest` on every production measurement subprocess."""
    import apt_engine.precondition as pre

    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="1 passed\n")

    monkeypatch.setattr(pre.subprocess, "run", fake_run)
    assert pre.pytest_runner(str(tmp_path)) == 0
    assert pre.pytest_collector(str(tmp_path)) == []
    assert pre.pytest_id_runner(["/tmp/test_x.py::test_ok"]) == 0

    assert len(calls) == 3
    for argv, _kwargs in calls:
        assert argv[:4] == [sys.executable, "-I", "-m", "pytest"]


def test_pytest_runner_ignores_pythonpath_pytest_shadow(tmp_path, monkeypatch):
    """A PYTHONPATH `pytest.py` must not forge a red target into exit zero."""
    import apt_engine.precondition as pre

    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "pytest.py").write_text("raise SystemExit(0)\n")
    target = tmp_path / "target"
    target.mkdir()
    (target / "test_red.py").write_text("def test_red():\n    assert False\n")
    monkeypatch.setenv("PYTHONPATH", str(shadow))

    assert pre.pytest_runner(str(target)) != 0
