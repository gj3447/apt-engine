"""ManifestSource seam (ADR-0003) — the pluggable trust root for the manifest."""

import json

from apt_engine.precondition import (
    FileManifestSource,
    ImpactReq,
    ImpactSpec,
    ManifestSource,
    evaluate_measured_mandated_from,
)


def test_file_source_is_a_manifest_source_and_loads(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"SCW->MetaReview": {"required": ["a.py::t"]}}))
    src = FileManifestSource(str(p))
    assert isinstance(src, ManifestSource)
    assert src.specs()["SCW->MetaReview"].required == (ImpactReq("a.py::t", None),)


def test_evaluate_from_a_custom_source(tmp_path):
    # Any object with specs() -> dict[str, ImpactSpec] plugs in at the seam
    # (a stand-in for a KG/CI source). Self-contained tmp test -> no PYTHONPATH dep.
    (tmp_path / "test_x.py").write_text("def test_ok():\n    assert True\n")

    class StubSource:
        def specs(self):
            return {
                "SCW->MetaReview": ImpactSpec(
                    ("SCW", "MetaReview"), (ImpactReq("test_x.py::test_ok"),)
                )
            }

    r = evaluate_measured_mandated_from("SCW", "MetaReview", target=str(tmp_path), source=StubSource())
    assert r.verdict.value == "PASS"


def test_source_error_fails_closed():
    class Boom:
        def specs(self):
            raise ValueError("source down")

    # A source outage = could-not-evaluate -> ERROR (PROM16 C4), still fail-closed.
    r = evaluate_measured_mandated_from("SCW", "MetaReview", target=".", source=Boom())
    assert r.verdict.value == "ERROR"


def test_non_measurable_transition_short_circuits_before_source():
    called = {"n": 0}

    class Counting:
        def specs(self):
            called["n"] += 1
            return {}

    r = evaluate_measured_mandated_from("SA", "SP", target=".", source=Counting())
    assert r.verdict.value == "FAIL"
    assert called["n"] == 0  # not measurable -> never touches the source
