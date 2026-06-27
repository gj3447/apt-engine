"""KgManifestSource — resolves the mandated manifest from the KG (non-caller).

Tested with a FAKE KgClient (canned rows): no live neo4j, no real impact run.
"""

import pytest

from apt_engine.contrib.kg_manifest import (
    KgManifestSource,
    _parse_neo4j_http_rows,
    http_kg_client,
)
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


# ---- HTTP KgClient (neo4j HTTP transactional API; reachable where bolt is not) ---- #

def test_http_parser_maps_neo4j_tx_response():
    payload = {
        "results": [{"columns": ["node_id", "sha256"], "data": [{"row": ["a.py::t", "deadbeef"]}]}],
        "errors": [],
    }
    assert _parse_neo4j_http_rows(payload) == [{"node_id": "a.py::t", "sha256": "deadbeef"}]


def test_http_parser_raises_on_neo4j_error():
    with pytest.raises(ValueError):
        _parse_neo4j_http_rows({"results": [], "errors": [{"code": "X", "message": "boom"}]})


def test_http_kg_client_posts_and_parses(monkeypatch):
    import json
    import urllib.request

    captured = {}

    class FakeResp:
        def __init__(self, data):
            self._d = data

        def read(self):
            return self._d

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        return FakeResp(
            json.dumps(
                {
                    "results": [
                        {
                            "columns": ["node_id", "sha256"],
                            "data": [{"row": ["impact/test_apt_contract.py::test_chain_is_canonical", "abc"]}],
                        }
                    ],
                    "errors": [],
                }
            ).encode()
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    src = KgManifestSource(client=http_kg_client("https://kg.example.com", auth=("u", "p")))
    assert isinstance(src, ManifestSource)
    assert src.specs()["SCW->MetaReview"].required == (
        ImpactReq("impact/test_apt_contract.py::test_chain_is_canonical", "abc"),
    )
    assert captured["url"].endswith("/db/neo4j/tx/commit")
    assert captured["body"]["statements"][0]["parameters"] == {
        "engine": "apt-engine",
        "transition": "SCW->MetaReview",
    }
