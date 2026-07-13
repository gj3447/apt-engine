"""H-C binding — EXACT node id + optional sha256 content pin (red-team HIGH-2 close).

Substring/name matching cannot stop a forge (a trivial test named to match
passes). So `required` is now exact `file.py::testname` node ids, optionally
sha256-pinned: with a sha, a same-named but different-content test is rejected.
Collector/runner/hasher are injected here (fakes); production uses real pytest.
"""

import json
from pathlib import Path

from apt_engine.precondition import (
    ImpactReq,
    ImpactSpec,
    evaluate_measured_default,
    evaluate_measured_mandated,
    evaluate_measured_mandated_default,
    load_impact_manifest,
    measure_mandated,
    pytest_collector,
)


def _collector(ids):
    return lambda target, rel_files=None: list(ids)


def _runner(code):
    return lambda node_ids: code


def _hasher(mapping):
    return lambda path: mapping.get(path, "UNKNOWN")


# ---- manifest parsing ---------------------------------------------------- #


def test_manifest_parses_exact_node_id_and_sha(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(
        json.dumps(
            {
                "SCW->MetaReview": {
                    "required": [
                        {"node_id": "test_scw.py::test_contract", "sha256": "abc"},
                        "test_other.py::test_x",
                    ]
                }
            }
        )
    )
    spec = load_impact_manifest(str(p))["SCW->MetaReview"]
    assert spec.required == (
        ImpactReq("test_scw.py::test_contract", "abc"),
        ImpactReq("test_other.py::test_x", None),
    )


def test_manifest_drops_bare_substrings_and_empty(tmp_path):
    # "impact" has no '::' -> rejected, so a bare name can never silently match.
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"SCW->MetaReview": {"required": ["impact", "", "f.py::t"]}}))
    assert load_impact_manifest(str(p))["SCW->MetaReview"].required == (ImpactReq("f.py::t", None),)


# ---- measure_mandated semantics ----------------------------------------- #


def test_unrelated_dir_missing_required_is_rejected():
    r = ImpactReq("test_scw.py::test_contract")
    ev = measure_mandated(
        "x",
        (r,),
        collector=_collector(["/abs/test_unrelated.py::test_ok"]),
        runner=_runner(0),
    )
    assert ev.met is False and ev.exit_code == 5


def test_exact_name_match_no_sha_passes():
    r = ImpactReq("test_scw.py::test_contract")
    ev = measure_mandated(
        "x",
        (r,),
        collector=_collector(["/abs/test_scw.py::test_contract"]),
        runner=_runner(0),
    )
    assert ev.met is True


def test_sha_match_passes():
    r = ImpactReq("test_scw.py::test_contract", "goodsha")
    ev = measure_mandated(
        "x",
        (r,),
        collector=_collector(["/abs/test_scw.py::test_contract"]),
        runner=_runner(0),
        hasher=_hasher({"/abs/test_scw.py": "goodsha"}),
    )
    assert ev.met is True


def test_sha_mismatch_is_content_forge_rejected():
    # SAME node id, WRONG content -> rejected (content-DRIFT vs a TRUSTED manifest).
    r = ImpactReq("test_scw.py::test_contract", "goodsha")
    ev = measure_mandated(
        "x",
        (r,),
        collector=_collector(["/abs/test_scw.py::test_contract"]),
        runner=_runner(0),
        hasher=_hasher({"/abs/test_scw.py": "FORGED"}),
    )
    assert ev.met is False and ev.exit_code == 6


def test_mandated_failing_run_is_unmet():
    r = ImpactReq("test_scw.py::test_contract")
    ev = measure_mandated(
        "x",
        (r,),
        collector=_collector(["/abs/test_scw.py::test_contract"]),
        runner=_runner(1),
    )
    assert ev.met is False


def test_all_required_must_be_present():
    reqs = (ImpactReq("a.py::t"), ImpactReq("b.py::t"))
    ev = measure_mandated("x", reqs, collector=_collector(["/abs/a.py::t"]), runner=_runner(0))
    assert ev.met is False and ev.exit_code == 5  # b.py::t missing


def test_runner_receives_exactly_the_matched_ids():
    # red-team MED-4: only the MANDATED node ids run, not all collected.
    seen = {}

    def recording_runner(ids):
        seen["ids"] = list(ids)
        return 0

    reqs = (ImpactReq("a.py::t"), ImpactReq("b.py::t"))
    measure_mandated(
        "x",
        reqs,
        collector=_collector(["/abs/a.py::t", "/abs/other.py::t", "/abs/b.py::t"]),
        runner=recording_runner,
    )
    assert sorted(seen["ids"]) == ["/abs/a.py::t", "/abs/b.py::t"]


def test_no_required_declared_is_unmet():
    ev = measure_mandated("x", (), collector=_collector(["/abs/a.py::t"]), runner=_runner(0))
    assert ev.met is False and ev.exit_code == 4


# ---- evaluate_measured_mandated ----------------------------------------- #


def test_evaluate_mandated_unknown_transition_fails_closed():
    r = evaluate_measured_mandated(
        "SCW",
        "MetaReview",
        target="x",
        manifest={},
        collector=_collector(["/abs/a.py::t"]),
        runner=_runner(0),
    )
    assert r.verdict.value == "FAIL"


def test_evaluate_mandated_genuine_pass_unlocks():
    m = {
        "SCW->MetaReview": ImpactSpec(
            ("SCW", "MetaReview"), (ImpactReq("test_scw.py::test_contract"),)
        )
    }
    r = evaluate_measured_mandated(
        "SCW",
        "MetaReview",
        target="x",
        manifest=m,
        collector=_collector(["/abs/test_scw.py::test_contract"]),
        runner=_runner(0),
    )
    assert r.verdict.value == "PASS"


def test_evaluate_mandated_content_forge_fails():
    m = {
        "SCW->MetaReview": ImpactSpec(
            ("SCW", "MetaReview"), (ImpactReq("test_scw.py::test_contract", "goodsha"),)
        )
    }
    r = evaluate_measured_mandated(
        "SCW",
        "MetaReview",
        target="x",
        manifest=m,
        collector=_collector(["/abs/test_scw.py::test_contract"]),
        runner=_runner(0),
        hasher=_hasher({"/abs/test_scw.py": "FORGED"}),
    )
    assert r.verdict.value == "FAIL"


# ---- production _default fail-closed ------------------------------------ #


def test_default_variant_fails_closed_for_non_measurable_transition():
    # red-team MED-5: is_measurable is enforced, not dead code.
    r = evaluate_measured_default("SA", "SP", target="x")
    assert r.verdict.value == "FAIL"
    assert "not locally measurable" in r.reason


def test_mandated_default_missing_manifest_fails_closed(tmp_path):
    # red-team LOW-7: a missing/unreadable manifest fails closed, not a traceback.
    # A missing manifest = could-not-evaluate -> ERROR (PROM16 C4), still
    # fail-closed (can_advance False), distinct from an evaluated FAIL.
    r = evaluate_measured_mandated_default(
        "SCW",
        "MetaReview",
        target=str(tmp_path),
        manifest_path=str(tmp_path / "nope.json"),
    )
    assert r.verdict.value == "ERROR"
    assert "unevaluable" in r.reason


def test_collector_works_under_ancestor_pytest_config(tmp_path):
    # red-team HIGH: pytest's rootdir is the nearest ancestor with config, NOT
    # `target`. A real project has pyproject at the ROOT; collecting a SUBDIR must
    # still yield runnable absolute ids (no path doubling). The old collector
    # produced /root/tests/impact/tests/impact/... which does not exist.
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    sub = tmp_path / "tests" / "impact"
    sub.mkdir(parents=True)
    (sub / "test_scw.py").write_text("def test_contract():\n    assert True\n")
    ids = pytest_collector(str(sub))
    assert ids, "collector returned nothing under an ancestor pytest config"
    for nid in ids:
        assert Path(nid.split("::", 1)[0]).is_file(), (
            f"collector produced a non-existent path: {nid}"
        )


def test_manifest_controlling_forger_passes_is_the_trust_boundary():
    # HONESTY (red-team MEDIUM): sha does NOT stop a forger who also writes the
    # manifest — they pin their own forged test's sha and pass. This is the
    # documented TRUST BOUNDARY (the manifest must come from a non-caller trust
    # root), not a bug. Asserting PASS here pins that boundary explicitly.
    forged_sha = "deadbeef"
    m = {
        "SCW->MetaReview": ImpactSpec(
            ("SCW", "MetaReview"), (ImpactReq("test_scw.py::test_contract", forged_sha),)
        )
    }
    r = evaluate_measured_mandated(
        "SCW",
        "MetaReview",
        target="x",
        manifest=m,
        collector=_collector(["/abs/test_scw.py::test_contract"]),
        runner=_runner(0),
        hasher=_hasher({"/abs/test_scw.py": forged_sha}),  # forger's own content hash
    )
    assert r.verdict.value == "PASS"  # the manifest is the trust root, by design


def test_basename_collision_fails_closed():
    # red-team LOW: two collected files share basename::func -> ambiguous -> fail.
    r = ImpactReq("test_scw.py::test_contract")
    ev = measure_mandated(
        "x",
        (r,),
        collector=_collector(["/a/test_scw.py::test_contract", "/b/test_scw.py::test_contract"]),
        runner=_runner(0),
    )
    assert ev.met is False and ev.exit_code == 7


def test_malformed_manifest_fails_closed(tmp_path):
    # red-team LOW: valid JSON but wrong shape must not crash (AttributeError).
    arr = tmp_path / "arr.json"
    arr.write_text(json.dumps(["SCW->MetaReview"]))  # a list, not a dict
    assert load_impact_manifest(str(arr)) == {}
    r = evaluate_measured_mandated_default(
        "SCW",
        "MetaReview",
        target=str(tmp_path),
        manifest_path=str(arr),
    )
    assert r.verdict.value == "FAIL"  # unknown transition -> fail closed, no traceback
