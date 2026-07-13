"""GateReceipt — auditable, replay-checkable record of a measured gate run.

Covers: receipt field assembly, JSON round-trip, the replay `audit_key()`
(volatile fields excluded), runner-tier detection, the new
`PreconditionEvidence` audit fields populated by `measure_mandated`, and the
end-to-end `*_with_receipt` gate + CLI `--receipt-out` paths.

# KG: rf-prom16-apt-gatereceipt-emitter (cycle prom16-apt-engine-hardening-2026-07-13)
"""

import json
from datetime import datetime, timezone

from apt_engine.gate import GateResult, Verdict, can_advance
from apt_engine.precondition import (
    FileManifestSource,
    ImpactReq,
    PreconditionEvidence,
    evaluate_measured_mandated_default,
    evaluate_measured_mandated_default_with_receipt,
    evaluate_measured_mandated_from_with_receipt,
    measure_mandated,
)
from apt_engine.receipt import (
    RECEIPT_SCHEMA_VERSION,
    GateReceipt,
    build_gate_receipt,
    runner_kind,
)

_FIXED = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)


def _clock():
    return _FIXED


# --------------------------------------------------------------------------- #
#  runner_kind                                                                 #
# --------------------------------------------------------------------------- #


def test_runner_kind_ci_when_ci_env_true():
    assert runner_kind({"CI": "true"}) == "ci"
    assert runner_kind({"CI": "TRUE"}) == "ci"
    assert runner_kind({"CI": "1"}) == "ci"


def test_runner_kind_local_when_absent_or_falsey():
    assert runner_kind({}) == "local"
    assert runner_kind({"CI": ""}) == "local"
    assert runner_kind({"CI": "false"}) == "local"
    assert runner_kind({"CI": "0"}) == "local"
    assert runner_kind({"CI": "no"}) == "local"


# --------------------------------------------------------------------------- #
#  build_gate_receipt — field assembly                                         #
# --------------------------------------------------------------------------- #


def _pass_result():
    return GateResult("SCW", "MetaReview", Verdict.PASS, "precondition satisfied")


def _evidence_green():
    return PreconditionEvidence(
        met=True,
        exit_code=0,
        source="impact:/base:1-mandated",
        matched_node_ids=("/base/test_x.py::t",),
        # observed shas are keyed by the DECLARED node id (portable), matching pins
        observed_shas=(("test_x.py::t", "deadbeef"),),
    )


def test_build_receipt_carries_measured_evidence():
    r = build_gate_receipt(
        _pass_result(),
        gate_kind="measured-mandated",
        target="/base",
        manifest_source_kind="FileManifestSource",
        evidence=_evidence_green(),
        required=(ImpactReq("test_x.py::t", sha256="deadbeef"),),
        env={"CI": "true"},
        clock=_clock,
    )
    assert isinstance(r, GateReceipt)
    assert r.schema_version == RECEIPT_SCHEMA_VERSION
    assert (r.from_phase, r.to_phase, r.verdict) == ("SCW", "MetaReview", "PASS")
    assert r.gate_kind == "measured-mandated"
    assert r.target == "/base"
    assert r.manifest_source_kind == "FileManifestSource"
    assert r.mandated_node_ids == ("test_x.py::t",)
    assert r.matched_node_ids == ("/base/test_x.py::t",)
    assert r.sha256_pinned == {"test_x.py::t": "deadbeef"}
    # observed is node_id-keyed, so it joins key-for-key with pinned
    assert r.sha256_observed == {"test_x.py::t": "deadbeef"}
    assert r.sha256_observed.keys() == r.sha256_pinned.keys()
    assert r.pytest_exit_code == 0
    assert r.evidence_source == "impact:/base:1-mandated"
    assert r.runner == "ci"
    assert r.timestamp_utc == _FIXED.isoformat()
    assert r.error is None


def test_build_receipt_without_evidence_is_still_valid():
    # unevaluable path: no measured evidence, still a full record. The unevaluable
    # verdict is ERROR (could-not-evaluate), not FAIL — see PROM16 C4.
    err = GateResult("SA", "SP", Verdict.ERROR, "impact gate unevaluable: boom")
    r = build_gate_receipt(
        err,
        gate_kind="measured-mandated",
        target="/base",
        manifest_source_kind="FileManifestSource",
        error="boom",
        clock=_clock,
    )
    assert r.verdict == "ERROR"
    assert r.mandated_node_ids == ()
    assert r.matched_node_ids == ()
    assert r.sha256_pinned == {} and r.sha256_observed == {}
    assert r.pytest_exit_code is None
    assert r.evidence_source is None
    assert r.error == "boom"


# --------------------------------------------------------------------------- #
#  JSON round-trip + audit_key                                                 #
# --------------------------------------------------------------------------- #


def test_to_json_round_trips():
    r = build_gate_receipt(
        _pass_result(),
        gate_kind="measured-mandated",
        target="/base",
        evidence=_evidence_green(),
        required=(ImpactReq("test_x.py::t", sha256="deadbeef"),),
        clock=_clock,
    )
    loaded = json.loads(r.to_json())
    assert loaded == r.to_dict()
    # tuples serialize as lists
    assert loaded["matched_node_ids"] == ["/base/test_x.py::t"]
    assert loaded["sha256_observed"] == {"test_x.py::t": "deadbeef"}


def test_audit_key_excludes_volatile_fields():
    # two runs of the SAME gate over the SAME evidence must compare equal for
    # replay, even though they ran at different times / on different runners.
    common = dict(
        gate_kind="measured-mandated",
        target="/base",
        manifest_source_kind="FileManifestSource",
        evidence=_evidence_green(),
        required=(ImpactReq("test_x.py::t", sha256="deadbeef"),),
    )
    a = build_gate_receipt(
        _pass_result(), **common, env={"CI": "true"}, clock=lambda: _FIXED
    )
    b = build_gate_receipt(
        _pass_result(),
        **common,
        env={},  # local runner
        clock=lambda: datetime(2027, 1, 1, tzinfo=timezone.utc),  # different time
    )
    assert a.runner != b.runner  # volatile fields DO differ
    assert a.timestamp_utc != b.timestamp_utc
    assert a.audit_key() == b.audit_key()  # ...but the reproducible fingerprint matches


def test_audit_key_differs_on_a_real_change():
    base = build_gate_receipt(
        _pass_result(),
        gate_kind="measured-mandated",
        target="/base",
        evidence=_evidence_green(),
        required=(ImpactReq("test_x.py::t", sha256="deadbeef"),),
        clock=_clock,
    )
    # a different observed sha (content drift) must change the audit key
    drifted_evidence = PreconditionEvidence(
        met=True,
        exit_code=0,
        source="impact:/base:1-mandated",
        matched_node_ids=("/base/test_x.py::t",),
        observed_shas=(("test_x.py::t", "CAFED00D"),),
    )
    drifted = build_gate_receipt(
        _pass_result(),
        gate_kind="measured-mandated",
        target="/base",
        evidence=drifted_evidence,
        required=(ImpactReq("test_x.py::t", sha256="deadbeef"),),
        clock=_clock,
    )
    assert base.audit_key() != drifted.audit_key()


# --------------------------------------------------------------------------- #
#  measure_mandated now surfaces matched ids + observed shas (fakes only)      #
# --------------------------------------------------------------------------- #


def test_measure_mandated_populates_audit_fields_on_green():
    required = (ImpactReq("test_x.py::t", sha256="abc"),)
    ev = measure_mandated(
        "/base",
        required,
        collector=lambda target, rel=None: ["/base/test_x.py::t"],
        runner=lambda ids: 0,
        hasher=lambda f: "abc",
    )
    assert ev.met is True
    assert ev.matched_node_ids == ("/base/test_x.py::t",)
    assert ev.observed_shas == (("test_x.py::t", "abc"),)  # node_id-keyed


def test_measure_mandated_records_observed_sha_on_mismatch():
    required = (ImpactReq("test_x.py::t", sha256="abc"),)
    ev = measure_mandated(
        "/base",
        required,
        collector=lambda target, rel=None: ["/base/test_x.py::t"],
        runner=lambda ids: 0,
        hasher=lambda f: "DIFFERENT",  # content forge
    )
    assert ev.met is False and ev.exit_code == 6
    # the receipt can now show pinned(abc) vs observed(DIFFERENT), joined by node_id
    assert ev.observed_shas == (("test_x.py::t", "DIFFERENT"),)


def test_measure_mandated_no_mandated_declared_has_empty_audit_fields():
    ev = measure_mandated(
        "/base", (), collector=lambda *a, **k: [], runner=lambda ids: 0
    )
    assert ev.exit_code == 4
    assert ev.matched_node_ids == () and ev.observed_shas == ()


# --------------------------------------------------------------------------- #
#  End-to-end: *_with_receipt over a real pytest run                           #
# --------------------------------------------------------------------------- #


def _sha_manifest(tmp_path, node_id, test_file):
    import hashlib

    man = tmp_path / "m.json"
    man.write_text(
        json.dumps(
            {
                "SCW->MetaReview": {
                    "required": [
                        {
                            "node_id": node_id,
                            "sha256": hashlib.sha256(test_file.read_bytes()).hexdigest(),
                        }
                    ]
                }
            }
        )
    )
    return man


def test_with_receipt_end_to_end_pass(tmp_path):
    import hashlib

    tf = tmp_path / "test_scw.py"
    tf.write_text("def test_contract():\n    assert True\n")
    man = _sha_manifest(tmp_path, "test_scw.py::test_contract", tf)
    result, receipt = evaluate_measured_mandated_default_with_receipt(
        "SCW", "MetaReview", target=str(tmp_path), manifest_path=str(man)
    )
    assert result.verdict is Verdict.PASS
    assert receipt.verdict == "PASS"
    assert receipt.gate_kind == "measured-mandated"
    assert receipt.manifest_source_kind == "FileManifestSource"
    assert receipt.mandated_node_ids == ("test_scw.py::test_contract",)
    assert len(receipt.matched_node_ids) == 1
    assert receipt.matched_node_ids[0].endswith("test_scw.py::test_contract")
    # observed sha equals the pinned one (no drift)
    observed = list(receipt.sha256_observed.values())
    assert observed == [hashlib.sha256(tf.read_bytes()).hexdigest()]
    assert receipt.pytest_exit_code == 0


def test_with_receipt_records_content_forge(tmp_path):
    # pinned sha of the canonical body, but the on-disk body differs -> FAIL,
    # and the receipt shows the OBSERVED (forged) sha, distinct from the pin.
    import hashlib

    canonical = b"def test_contract():\n    assert True\n"
    tf = tmp_path / "test_scw.py"
    tf.write_text("def test_contract():\n    assert True  # forged\n")
    man = tmp_path / "m.json"
    man.write_text(
        json.dumps(
            {
                "SCW->MetaReview": {
                    "required": [
                        {
                            "node_id": "test_scw.py::test_contract",
                            "sha256": hashlib.sha256(canonical).hexdigest(),
                        }
                    ]
                }
            }
        )
    )
    result, receipt = evaluate_measured_mandated_default_with_receipt(
        "SCW", "MetaReview", target=str(tmp_path), manifest_path=str(man)
    )
    assert result.verdict is Verdict.FAIL
    assert receipt.pytest_exit_code == 6  # sha-mismatch signal
    pinned = list(receipt.sha256_pinned.values())[0]
    observed = list(receipt.sha256_observed.values())[0]
    assert observed != pinned  # the receipt makes the drift auditable


def test_plain_and_with_receipt_agree_on_verdict(tmp_path):
    # delegation regression: the plain function must give the SAME verdict/reason
    # as the receipt variant (the plain one just drops the receipt).
    tf = tmp_path / "test_scw.py"
    tf.write_text("def test_contract():\n    assert True\n")
    man = _sha_manifest(tmp_path, "test_scw.py::test_contract", tf)
    plain = evaluate_measured_mandated_default(
        "SCW", "MetaReview", target=str(tmp_path), manifest_path=str(man)
    )
    result, _ = evaluate_measured_mandated_default_with_receipt(
        "SCW", "MetaReview", target=str(tmp_path), manifest_path=str(man)
    )
    assert plain.verdict == result.verdict
    assert plain.reason == result.reason


def test_not_measurable_transition_still_emits_receipt(tmp_path):
    # SA->SP is not locally measurable: the guard FAILs before the manifest is
    # even read, but a receipt is still emitted (a FAIL is as auditable as a PASS).
    result, receipt = evaluate_measured_mandated_from_with_receipt(
        "SA",
        "SP",
        target=str(tmp_path),
        source=FileManifestSource(str(tmp_path / "does-not-exist.json")),
    )
    assert result.verdict is Verdict.FAIL
    assert "not locally measurable" in receipt.reason
    assert receipt.gate_kind == "measured-mandated"
    assert receipt.manifest_source_kind == "FileManifestSource"
    assert receipt.pytest_exit_code is None
    assert receipt.error is None


def test_unevaluable_manifest_sets_receipt_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json")
    result, receipt = evaluate_measured_mandated_default_with_receipt(
        "SCW", "MetaReview", target=str(tmp_path), manifest_path=str(bad)
    )
    # Malformed manifest = could-not-evaluate -> ERROR (PROM16 C4), still
    # fail-closed. The receipt carries the underlying error for audit.
    assert result.verdict is Verdict.ERROR
    assert not can_advance(result.verdict)  # ERROR never unlocks downstream
    assert receipt.error is not None
    assert "unevaluable" in receipt.reason


# --------------------------------------------------------------------------- #
#  CLI --receipt-out                                                           #
# --------------------------------------------------------------------------- #


def test_cli_receipt_out_writes_valid_json(tmp_path, capsys):
    import hashlib

    from apt_engine.cli import main

    tf = tmp_path / "test_scw.py"
    tf.write_text("def test_contract():\n    assert True\n")
    man = tmp_path / "m.json"
    man.write_text(
        json.dumps(
            {
                "SCW->MetaReview": {
                    "required": [
                        {
                            "node_id": "test_scw.py::test_contract",
                            "sha256": hashlib.sha256(tf.read_bytes()).hexdigest(),
                        }
                    ]
                }
            }
        )
    )
    out = tmp_path / "receipt.json"
    rc = main(
        [
            "gate",
            "SCW",
            "MetaReview",
            "--measure",
            str(tmp_path),
            "--impact-manifest",
            str(man),
            "--receipt-out",
            str(out),
        ]
    )
    capsys.readouterr()
    assert rc == 0
    assert out.is_file()
    doc = json.loads(out.read_text())
    assert doc["verdict"] == "PASS"
    assert doc["gate_kind"] == "measured-mandated"
    assert doc["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert doc["mandated_node_ids"] == ["test_scw.py::test_contract"]


def test_cli_without_receipt_out_writes_nothing(tmp_path, capsys):
    from apt_engine.cli import main

    rc = main(["gate", "SA", "SP", "--precondition-met"])
    capsys.readouterr()
    assert rc == 0
    # no receipt file should have been created anywhere in tmp_path
    assert not list(tmp_path.glob("*.json"))


# --------------------------------------------------------------------------- #
#  review-hardening: red-with-matched, bare/asserted paths, checkout portability #
# --------------------------------------------------------------------------- #


def test_receipt_over_a_matched_but_RED_mandated_run(tmp_path):
    # the flagship FAIL case the first cut never asserted: the mandated tests are
    # FOUND (matched non-empty) but RUN RED (exit != 0). The receipt must record
    # a FAIL verdict WITH the matched ids + the real exit code + observed sha.
    required = (ImpactReq("test_x.py::t", sha256="abc"),)
    ev = measure_mandated(
        "/base",
        required,
        collector=lambda target, rel=None: ["/base/test_x.py::t"],
        runner=lambda ids: 1,  # tests matched, but the run is RED
        hasher=lambda f: "abc",
    )
    assert ev.met is False and ev.exit_code == 1
    assert ev.matched_node_ids == ("/base/test_x.py::t",)  # matched, despite red
    receipt = build_gate_receipt(
        GateResult("SCW", "MetaReview", Verdict.FAIL, "precondition unmet"),
        gate_kind="measured-mandated",
        target="/base",
        evidence=ev,
        required=required,
        clock=_clock,
    )
    assert receipt.verdict == "FAIL"
    assert receipt.matched_node_ids == ("/base/test_x.py::t",)  # non-empty on FAIL
    assert receipt.pytest_exit_code == 1
    assert receipt.sha256_observed == {"test_x.py::t": "abc"}


def test_cli_receipt_out_asserted_path(tmp_path, capsys):
    from apt_engine.cli import main

    out = tmp_path / "r.json"
    rc = main(["gate", "SA", "SP", "--precondition-met", "--receipt-out", str(out)])
    capsys.readouterr()
    assert rc == 0
    doc = json.loads(out.read_text())
    assert doc["gate_kind"] == "asserted"
    assert doc["verdict"] == "PASS"
    assert doc["pytest_exit_code"] is None  # nothing measured on the asserted path
    assert doc["mandated_node_ids"] == []


def test_cli_receipt_out_bare_path_records_exit_code(tmp_path, capsys):
    # review B fix: the bare measured path's receipt carries the REAL pytest exit
    # code (0 on a passing run), not None.
    from apt_engine.cli import main

    (tmp_path / "test_green.py").write_text("def test_ok():\n    assert True\n")
    out = tmp_path / "r.json"
    rc = main(
        ["gate", "SCW", "MetaReview", "--measure", str(tmp_path), "--receipt-out", str(out)]
    )
    capsys.readouterr()
    assert rc == 0
    doc = json.loads(out.read_text())
    assert doc["gate_kind"] == "measured-bare"
    assert doc["verdict"] == "PASS"
    assert doc["pytest_exit_code"] == 0  # not None — a real run happened
    assert doc["evidence_source"] is not None


def test_mcp_gate_measured_bare_carries_receipt(tmp_path):
    from apt_engine.frontends.mcp_server import build_tools

    (tmp_path / "test_green.py").write_text("def test_ok():\n    assert True\n")
    tool = build_tools()["apt_gate_measured"]
    resp = tool("SCW", "MetaReview", str(tmp_path))
    assert resp["verdict"] == "PASS"
    assert resp["receipt"]["gate_kind"] == "measured-bare"
    assert resp["receipt"]["pytest_exit_code"] == 0


def test_audit_key_is_checkout_portable():
    # THE fix for review finding A/C: two runs of the SAME decision over the SAME
    # declared manifest + SAME test content, but at DIFFERENT checkout paths
    # (different target + different absolute matched ids), must compare EQUAL —
    # otherwise a future `verify --replay` reports false drift ci-vs-local.
    pinned = (ImpactReq("test_x.py::t", sha256="abc"),)
    a = build_gate_receipt(
        GateResult("SCW", "MetaReview", Verdict.PASS, "ok"),
        gate_kind="measured-mandated",
        target="/home/alice/repo/tests",
        manifest_source_kind="FileManifestSource",
        evidence=PreconditionEvidence(
            met=True,
            exit_code=0,
            source="impact:/home/alice/repo/tests:1-mandated",
            matched_node_ids=("/home/alice/repo/tests/test_x.py::t",),
            observed_shas=(("test_x.py::t", "abc"),),
        ),
        required=pinned,
        clock=_clock,
    )
    b = build_gate_receipt(
        GateResult("SCW", "MetaReview", Verdict.PASS, "ok"),
        gate_kind="measured-mandated",
        target="/ci/runner/work/repo/tests",  # different checkout
        manifest_source_kind="FileManifestSource",
        evidence=PreconditionEvidence(
            met=True,
            exit_code=0,
            source="impact:/ci/runner/work/repo/tests:1-mandated",
            matched_node_ids=("/ci/runner/work/repo/tests/test_x.py::t",),  # different abs
            observed_shas=(("test_x.py::t", "abc"),),  # same content, portable key
        ),
        required=pinned,
        clock=_clock,
    )
    assert a.target != b.target  # checkout-specific fields DO differ
    assert a.matched_node_ids != b.matched_node_ids
    assert a.audit_key() == b.audit_key()  # ...but the portable fingerprint matches


def _receipt_with_shas(pinned_items, observed_items):
    # construct directly so only the sha-dict INSERTION ORDER differs; all
    # ordered tuple fields (mandated/matched) are held identical.
    return GateReceipt(
        schema_version=RECEIPT_SCHEMA_VERSION,
        from_phase="SCW",
        to_phase="MetaReview",
        verdict="PASS",
        gate_kind="measured-mandated",
        reason="ok",
        gate_version=None,
        target="/base",
        manifest_source_kind="FileManifestSource",
        mandated_node_ids=("a.py::t1", "b.py::t2"),
        matched_node_ids=("/base/a.py::t1", "/base/b.py::t2"),
        sha256_pinned=dict(pinned_items),
        sha256_observed=dict(observed_items),
        pytest_exit_code=0,
        evidence_source="impact:/base:2-mandated",
        runner="local",
        timestamp_utc=_FIXED.isoformat(),
        python_version="3.12.0",
        apt_engine_version="0.1.0",
        error=None,
    )


def test_audit_key_and_json_stable_across_dict_insertion_order():
    # multi-entry sha dicts inserted in OPPOSITE order (everything else identical)
    # must yield the same audit_key (sorted items) AND byte-identical to_json
    # (sort_keys) — the order-independence that makes replay sound for >1 test.
    fwd = _receipt_with_shas(
        [("a.py::t1", "h1"), ("b.py::t2", "h2")],
        [("a.py::t1", "h1"), ("b.py::t2", "h2")],
    )
    rev = _receipt_with_shas(
        [("b.py::t2", "h2"), ("a.py::t1", "h1")],
        [("b.py::t2", "h2"), ("a.py::t1", "h1")],
    )
    # dicts are equal but built in different insertion order
    assert list(fwd.sha256_pinned) != list(rev.sha256_pinned)
    assert fwd.audit_key() == rev.audit_key()
    assert fwd.to_json() == rev.to_json()
