"""KgManifestSource — resolves the mandated manifest from the KG (non-caller).

Tested with a FAKE KgClient (canned rows): no live neo4j, no real impact run.
"""

from apt_engine.contrib.kg_manifest import KgManifestSource
from apt_engine.precondition import (
    ImpactReq,
    ManifestSource,
    evaluate_measured_mandated_from,
)


class FakeKg:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def run(self, query, params):
        self.calls.append((query, params))
        return list(self.rows)


def test_kg_source_builds_specs_and_queries_correctly():
    fake = FakeKg(
        [{"node_id": "impact/test_apt_contract.py::test_chain_is_canonical", "sha256": "abc"}]
    )
    src = KgManifestSource(client=fake)
    assert isinstance(src, ManifestSource)
    specs = src.specs()
    assert specs["SCW->MetaReview"].required == (
        ImpactReq("impact/test_apt_contract.py::test_chain_is_canonical", "abc"),
    )
    # queried the right engine + transition, against the MANDATES_IMPACT contract
    assert fake.calls[0][1] == {"engine": "apt-engine", "transition": "SCW->MetaReview"}
    assert "MANDATES_IMPACT" in fake.calls[0][0]


def test_kg_source_backend_error_fails_closed():
    class Boom:
        def run(self, query, params):
            raise RuntimeError("bolt down")

    r = evaluate_measured_mandated_from(
        "SCW", "MetaReview", target=".", source=KgManifestSource(client=Boom())
    )
    assert r.verdict.value == "FAIL"  # ValueError translated -> fail closed


def test_kg_source_empty_rows_fail_closed(tmp_path):
    r = evaluate_measured_mandated_from(
        "SCW", "MetaReview", target=str(tmp_path), source=KgManifestSource(client=FakeKg([]))
    )
    assert r.verdict.value == "FAIL"  # no mandated tests declared -> not met
