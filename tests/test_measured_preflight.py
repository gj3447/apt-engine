"""Measured wrappers must validate gate structure before touching external I/O.

# KG: TASK_apt_engine_measured_gate_preflight_order_2026_07_13
# KG: CONTRACT_apt_engine_measured_gate_preflight_order_2026_07_13
"""

import pytest

import apt_engine.precondition as pre
from apt_engine.gate import Verdict, evaluate_transition


def _unexpected_io(*_args, **_kwargs):
    raise AssertionError("external I/O ran before gate preflight")


_PUBLIC_ENTRIES = (
    "evaluate_measured",
    "evaluate_measured_default",
    "evaluate_measured_default_with_receipt",
    "evaluate_measured_mandated",
    "evaluate_measured_mandated_from",
    "evaluate_measured_mandated_from_with_receipt",
    "evaluate_measured_mandated_default",
    "evaluate_measured_mandated_default_with_receipt",
)

_EXPECTED_CONDITIONAL_CALLS = {
    "evaluate_measured": ["runner"],
    "evaluate_measured_default": ["runner"],
    "evaluate_measured_default_with_receipt": ["runner"],
    "evaluate_measured_mandated": ["collector", "runner"],
    "evaluate_measured_mandated_from": ["source", "collector", "runner"],
    "evaluate_measured_mandated_from_with_receipt": ["source", "collector", "runner"],
    "evaluate_measured_mandated_default": ["file-source", "collector", "runner"],
    "evaluate_measured_mandated_default_with_receipt": [
        "file-source",
        "collector",
        "runner",
    ],
}


def _invoke_entry(
    name,
    from_phase,
    to_phase,
    *,
    runner,
    collector,
    source,
    conditional=False,
    skipped=False,
):
    required = (pre.ImpactReq("test_x.py::test_x"),)
    manifest = {f"{from_phase}->{to_phase}": pre.ImpactSpec((from_phase, to_phase), required)}
    common = {
        "target": "unused",
        "conditional": conditional,
        "skipped": skipped,
    }
    if name == "evaluate_measured":
        output = pre.evaluate_measured(from_phase, to_phase, runner=runner, **common)
    elif name in ("evaluate_measured_default", "evaluate_measured_default_with_receipt"):
        output = getattr(pre, name)(from_phase, to_phase, **common)
    elif name == "evaluate_measured_mandated":
        output = pre.evaluate_measured_mandated(
            from_phase,
            to_phase,
            manifest=manifest,
            collector=collector,
            runner=runner,
            **common,
        )
    elif name in (
        "evaluate_measured_mandated_from",
        "evaluate_measured_mandated_from_with_receipt",
    ):
        output = getattr(pre, name)(from_phase, to_phase, source=source, **common)
    else:
        output = getattr(pre, name)(from_phase, to_phase, manifest_path="unused.json", **common)
    return output[0] if isinstance(output, tuple) else output


def test_evaluate_measured_skip_does_not_call_injected_runner():
    result = pre.evaluate_measured("SP", "ST", runner=_unexpected_io, target="unused", skipped=True)
    assert result.verdict is Verdict.SKIP


def test_evaluate_measured_default_unknown_phase_raises_before_pytest(monkeypatch):
    monkeypatch.setattr(pre, "pytest_runner", _unexpected_io)
    with pytest.raises(KeyError, match="unknown APT phase"):
        pre.evaluate_measured_default("UNKNOWN", "SP", target="unused")


def test_evaluate_measured_mandated_skip_does_not_collect_or_run():
    manifest = {"SP->ST": pre.ImpactSpec(("SP", "ST"), (pre.ImpactReq("test_x.py::test_x"),))}
    result = pre.evaluate_measured_mandated(
        "SP",
        "ST",
        target="unused",
        manifest=manifest,
        collector=_unexpected_io,
        runner=_unexpected_io,
        skipped=True,
    )
    assert result.verdict is Verdict.SKIP


def test_source_receipt_conflict_raises_before_source_and_outside_error_catch():
    class UnexpectedSource:
        def specs(self):
            raise ValueError("source should not be called")

    with pytest.raises(ValueError, match="mutually exclusive"):
        pre.evaluate_measured_mandated_from_with_receipt(
            "SCW",
            "MetaReview",
            target="unused",
            source=UnexpectedSource(),
            conditional=True,
            skipped=True,
        )


@pytest.mark.parametrize(
    ("from_phase", "to_phase", "skipped", "expected"),
    [
        ("MetaReview", "MetaReview", False, Verdict.FAIL),
        ("SA", "ST", False, Verdict.FAIL),
        ("SP", "ST", True, Verdict.SKIP),
    ],
)
def test_all_eight_public_entries_settle_structural_results_before_io(
    monkeypatch, from_phase, to_phase, skipped, expected
):
    class UnexpectedSource:
        def specs(self):
            return _unexpected_io()

    monkeypatch.setattr(pre, "pytest_runner", _unexpected_io)
    monkeypatch.setattr(pre, "pytest_collector", _unexpected_io)
    monkeypatch.setattr(pre, "pytest_id_runner", _unexpected_io)
    monkeypatch.setattr(pre.FileManifestSource, "specs", _unexpected_io)

    for name in _PUBLIC_ENTRIES:
        result = _invoke_entry(
            name,
            from_phase,
            to_phase,
            runner=_unexpected_io,
            collector=_unexpected_io,
            source=UnexpectedSource(),
            skipped=skipped,
        )
        assert result.verdict is expected, name


@pytest.mark.parametrize("name", _PUBLIC_ENTRIES)
@pytest.mark.parametrize(
    ("from_phase", "to_phase", "conditional", "skipped", "error"),
    [
        ("UNKNOWN", "SP", False, False, KeyError),
        ("SP", "ST", True, True, ValueError),
    ],
)
def test_all_eight_public_entries_raise_caller_bugs_before_io(
    monkeypatch, name, from_phase, to_phase, conditional, skipped, error
):
    class UnexpectedSource:
        def specs(self):
            return _unexpected_io()

    monkeypatch.setattr(pre, "pytest_runner", _unexpected_io)
    monkeypatch.setattr(pre, "pytest_collector", _unexpected_io)
    monkeypatch.setattr(pre, "pytest_id_runner", _unexpected_io)
    monkeypatch.setattr(pre.FileManifestSource, "specs", _unexpected_io)

    with pytest.raises(error):
        _invoke_entry(
            name,
            from_phase,
            to_phase,
            runner=_unexpected_io,
            collector=_unexpected_io,
            source=UnexpectedSource(),
            conditional=conditional,
            skipped=skipped,
        )


def test_six_production_entries_keep_known_non_measurable_fail_without_io(monkeypatch):
    class UnexpectedSource:
        def specs(self):
            return _unexpected_io()

    monkeypatch.setattr(pre, "pytest_runner", _unexpected_io)
    monkeypatch.setattr(pre, "pytest_collector", _unexpected_io)
    monkeypatch.setattr(pre, "pytest_id_runner", _unexpected_io)
    monkeypatch.setattr(pre.FileManifestSource, "specs", _unexpected_io)

    production_entries = tuple(
        n for n in _PUBLIC_ENTRIES if n not in {"evaluate_measured", "evaluate_measured_mandated"}
    )
    assert evaluate_transition("SA", "SP", precondition_met=True).verdict is Verdict.PASS
    for name in production_entries:
        result = _invoke_entry(
            name,
            "SA",
            "SP",
            runner=_unexpected_io,
            collector=_unexpected_io,
            source=UnexpectedSource(),
        )
        assert result.verdict is Verdict.FAIL, name
        assert "not locally measurable" in result.reason, name


@pytest.mark.parametrize("name", _PUBLIC_ENTRIES)
@pytest.mark.parametrize(("exit_code", "expected"), [(0, Verdict.CONDITIONAL), (1, Verdict.FAIL)])
def test_conditional_still_measures_once_on_all_public_entries(
    monkeypatch, name, exit_code, expected
):
    calls = []
    required = (pre.ImpactReq("test_x.py::test_x"),)
    manifest = {"SCW->MetaReview": pre.ImpactSpec(("SCW", "MetaReview"), required)}

    def runner(_target):
        calls.append("runner")
        return exit_code

    def collector(_target, _rel_files=None):
        calls.append("collector")
        return ["/abs/test_x.py::test_x"]

    class Source:
        def specs(self):
            calls.append("source")
            return manifest

    def file_specs(_self):
        calls.append("file-source")
        return manifest

    monkeypatch.setattr(pre, "pytest_runner", runner)
    monkeypatch.setattr(pre, "pytest_collector", collector)
    monkeypatch.setattr(pre, "pytest_id_runner", runner)
    monkeypatch.setattr(pre.FileManifestSource, "specs", file_specs)
    result = _invoke_entry(
        name,
        "SCW",
        "MetaReview",
        runner=runner,
        collector=collector,
        source=Source(),
        conditional=True,
    )
    assert result.verdict is expected
    assert calls == _EXPECTED_CONDITIONAL_CALLS[name]


@pytest.mark.parametrize(
    ("from_phase", "to_phase", "conditional", "skipped"),
    [
        ("MetaReview", "MetaReview", False, False),
        ("SA", "ST", False, False),
        ("SP", "ST", False, True),
    ],
)
def test_structural_gate_result_is_repeatable_and_independent_of_measured_truth(
    from_phase, to_phase, conditional, skipped
):
    results = [
        evaluate_transition(
            from_phase,
            to_phase,
            precondition_met=precondition_met,
            conditional=conditional,
            skipped=skipped,
        )
        for precondition_met in (False, True, True)
    ]
    assert results[0] == results[1] == results[2]


@pytest.mark.parametrize("precondition_met", [False, True])
def test_conflicting_flags_raise_the_same_error_before_phase_lookup(precondition_met):
    with pytest.raises(ValueError, match="mutually exclusive") as caught:
        evaluate_transition(
            "UNKNOWN",
            "ALSO_UNKNOWN",
            precondition_met=precondition_met,
            conditional=True,
            skipped=True,
        )
    assert str(caught.value) == (
        "conditional and skipped are mutually exclusive: a skipped transition "
        "was never evaluated, a conditional one was — pass at most one"
    )


@pytest.mark.parametrize(("from_phase", "to_phase"), [("UNKNOWN", "SP"), ("SA", "UNKNOWN")])
def test_unknown_phase_error_is_independent_of_measured_truth(from_phase, to_phase):
    errors = []
    for precondition_met in (False, True):
        with pytest.raises(KeyError) as caught:
            evaluate_transition(from_phase, to_phase, precondition_met=precondition_met)
        errors.append(str(caught.value))
    assert errors[0] == errors[1]
