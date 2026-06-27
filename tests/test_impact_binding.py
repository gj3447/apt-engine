"""H-C fix harness (red-team follow-up) — bind --measure TARGET to MANDATED tests.

The red-team found the measured gate passed on ANY passing dir: pointing
`--measure` at an unrelated trivially-passing test satisfied SCW->MetaReview even
though the phase's mandated TDAD impact_tests never ran. These RED tests pin the
fix: the precondition is met only when the tests the transition MANDATES (declared
in a manifest, not chosen by the caller) are actually collected under the target
AND pass. An unrelated passing dir is rejected.

Collector/runner are injected here (fakes); production uses real pytest subprocess.
"""

import json


from apt_engine.precondition import (
    ImpactSpec,
    evaluate_measured_default,
    evaluate_measured_mandated,
    evaluate_measured_mandated_default,
    load_impact_manifest,
    measure_mandated,
)


def _collector(ids):
    return lambda target: list(ids)


def _runner(code):
    return lambda node_ids: code


def test_manifest_loads_required_per_transition(tmp_path):
    p = tmp_path / "apt-impact.json"
    p.write_text(json.dumps({"SCW->MetaReview": {"required": ["impact"]}}))
    m = load_impact_manifest(str(p))
    assert isinstance(m["SCW->MetaReview"], ImpactSpec)
    assert m["SCW->MetaReview"].required == ("impact",)


def test_unrelated_passing_dir_is_rejected():
    # THE forge: a passing dir with NO mandated test must be UNMET.
    ev = measure_mandated(
        "x", ("impact",),
        collector=_collector(["x/test_unrelated.py::test_ok"]), runner=_runner(0),
    )
    assert ev.met is False


def test_mandated_tests_present_and_passing_is_met():
    ev = measure_mandated(
        "x", ("impact",),
        collector=_collector(["x/test_impact.py::test_scw_impact"]), runner=_runner(0),
    )
    assert ev.met is True


def test_mandated_tests_present_but_failing_is_unmet():
    ev = measure_mandated(
        "x", ("impact",),
        collector=_collector(["x/test_impact.py::test_scw_impact"]), runner=_runner(1),
    )
    assert ev.met is False


def test_no_required_declared_is_unmet():
    ev = measure_mandated("x", (), collector=_collector(["x/test_impact.py::test_x"]), runner=_runner(0))
    assert ev.met is False


def test_evaluate_mandated_unknown_transition_fails_closed():
    # No manifest entry for the transition -> cannot measure -> FAIL (fail-closed).
    r = evaluate_measured_mandated(
        "SCW", "MetaReview", target="x", manifest={},
        collector=_collector(["x/test_impact.py::test_scw_impact"]), runner=_runner(0),
    )
    assert r.verdict.value == "FAIL"


def test_evaluate_mandated_forge_rejected_yields_fail():
    m = {"SCW->MetaReview": ImpactSpec(("SCW", "MetaReview"), ("impact",))}
    r = evaluate_measured_mandated(
        "SCW", "MetaReview", target="x", manifest=m,
        collector=_collector(["x/test_unrelated.py::test_ok"]), runner=_runner(0),
    )
    assert r.verdict.value == "FAIL"  # unrelated passing dir does NOT satisfy


def test_evaluate_mandated_name_matching_pass_unlocks():
    # A passing test whose node id MATCHES the mandated substring unlocks it.
    # NB: binding is name-based — this proves the mechanism, not that the test
    # did "real" impact work (red-team HIGH-2; exact node-id binding is follow-up).
    m = {"SCW->MetaReview": ImpactSpec(("SCW", "MetaReview"), ("impact",))}
    r = evaluate_measured_mandated(
        "SCW", "MetaReview", target="x", manifest=m,
        collector=_collector(["x/test_impact.py::test_scw_impact"]), runner=_runner(0),
    )
    assert r.verdict.value == "PASS"


def test_empty_substring_required_is_rejected():
    # red-team HIGH-1: required=[""] would match every node id -> must NOT pass.
    ev = measure_mandated(
        "x", ("",), collector=_collector(["x/test_anything.py::test_ok"]), runner=_runner(0),
    )
    assert ev.met is False


def test_manifest_drops_empty_and_whitespace_substrings(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"SCW->MetaReview": {"required": ["", "  ", "impact"]}}))
    assert load_impact_manifest(str(p))["SCW->MetaReview"].required == ("impact",)


def test_runner_receives_exactly_the_matched_subset():
    # red-team MED-4: only the MANDATED node ids run, not all collected.
    seen = {}

    def recording_runner(ids):
        seen["ids"] = list(ids)
        return 0

    measure_mandated(
        "x", ("impact",),
        collector=_collector(
            ["x/test_impact_a.py::t", "x/test_other.py::t", "x/test_impact_b.py::t"]
        ),
        runner=recording_runner,
    )
    assert seen["ids"] == ["x/test_impact_a.py::t", "x/test_impact_b.py::t"]


def test_default_variant_fails_closed_for_non_measurable_transition():
    # red-team MED-5: is_measurable is now enforced, not dead code.
    r = evaluate_measured_default("SA", "SP", target="x")
    assert r.verdict.value == "FAIL"
    assert "not locally measurable" in r.reason


def test_mandated_default_missing_manifest_fails_closed(tmp_path):
    # red-team LOW-7: a missing/unreadable manifest fails closed, not a traceback.
    r = evaluate_measured_mandated_default(
        "SCW", "MetaReview", target=str(tmp_path), manifest_path=str(tmp_path / "nope.json"),
    )
    assert r.verdict.value == "FAIL"
    assert "unreadable" in r.reason
