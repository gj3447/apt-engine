"""Deterministic receipt replay verification (apt_engine.replay) — both directions.

GAP-2: `verify --replay` was described in receipt.py but not implemented. These
tests pin: a faithful receipt replays verified, and EVERY tampering / drift / I/O
failure fails closed (replay_verified=False + a typed Mismatch, never an exception,
never a silent pass). No pytest is re-run during replay.
"""

import hashlib
import json

import pytest

from apt_engine.precondition import (
    FileManifestSource,
    evaluate_measured_mandated_from_with_receipt,
)
from apt_engine.replay import MismatchKind, verify_replay, verify_replay_file


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pass_receipt(tmp_path, *, pinned=True):
    """Produce a REAL passing mandated-gate receipt (one real pytest run)."""
    tf = tmp_path / "test_ok.py"
    tf.write_text("def test_ok():\n    assert True\n")
    req = {"node_id": "test_ok.py::test_ok"}
    if pinned:
        req["sha256"] = _sha(tf)
    man = tmp_path / "m.json"
    man.write_text(json.dumps({"SCW->MetaReview": {"required": [req]}}))
    result, receipt = evaluate_measured_mandated_from_with_receipt(
        "SCW", "MetaReview", target=str(tmp_path), source=FileManifestSource(str(man))
    )
    assert result.verdict.value == "PASS"  # precondition for the replay tests below
    return receipt, tf


def _fail_receipt(tmp_path):
    """Produce a REAL exit-nonzero FAIL receipt (a mandated node id that never
    collects -> measure_mandated exit 5 -> FAIL, error=None)."""
    tf = tmp_path / "test_ok.py"
    tf.write_text("def test_ok():\n    assert True\n")
    man = tmp_path / "m.json"
    man.write_text(json.dumps({"SCW->MetaReview": {"required": ["test_ok.py::test_absent"]}}))
    result, receipt = evaluate_measured_mandated_from_with_receipt(
        "SCW", "MetaReview", target=str(tmp_path), source=FileManifestSource(str(man))
    )
    assert result.verdict.value == "FAIL"  # precondition for the tests below
    assert receipt.pytest_exit_code not in (None, 0) and receipt.error is None
    return receipt


def _write(tmp_path, receipt):
    p = tmp_path / "receipt.json"
    p.write_text(receipt.to_json())
    return p


def _kinds(result):
    return {m.kind for m in result.mismatches}


# --- verified direction ---------------------------------------------------- #


def test_faithful_pass_receipt_replays_verified(tmp_path):
    receipt, _ = _pass_receipt(tmp_path)
    path = _write(tmp_path, receipt)
    result = verify_replay_file(str(path))
    assert result.replay_verified is True
    assert result.mismatches == ()
    assert result.recomputed_verdict == "PASS"
    assert result.stored_audit_key == result.recomputed_audit_key
    assert result.transition == "SCW->MetaReview"


def test_name_only_receipt_replays_verified(tmp_path):
    # no sha pin -> no observed shas to re-check; verdict re-eval + audit_key only.
    receipt, _ = _pass_receipt(tmp_path, pinned=False)
    path = _write(tmp_path, receipt)
    result = verify_replay_file(str(path))
    assert result.replay_verified is True
    assert result.recomputed_verdict == "PASS"


def test_error_receipt_replays_verified(tmp_path):
    # a could-not-evaluate ERROR receipt (missing manifest) must itself replay: the
    # recorded error re-derives to ERROR and there are no pinned files to drift.
    _, receipt = evaluate_measured_mandated_from_with_receipt(
        "SCW", "MetaReview", target=str(tmp_path),
        source=FileManifestSource(str(tmp_path / "missing.json")),
    )
    assert receipt.verdict == "ERROR" and receipt.error
    path = _write(tmp_path, receipt)
    result = verify_replay_file(str(path))
    assert result.replay_verified is True
    assert result.recomputed_verdict == "ERROR"


def test_checkout_override_resolves_files(tmp_path):
    receipt, tf = _pass_receipt(tmp_path)
    # move the checkout: same relative layout, different root
    moved = tmp_path / "elsewhere"
    moved.mkdir()
    (moved / "test_ok.py").write_text(tf.read_text())
    path = _write(tmp_path, receipt)
    result = verify_replay_file(str(path), checkout=str(moved))
    assert result.replay_verified is True


# --- fail-closed direction ------------------------------------------------- #


def test_content_drift_fails_closed(tmp_path):
    receipt, tf = _pass_receipt(tmp_path)
    path = _write(tmp_path, receipt)
    tf.write_text("def test_ok():\n    assert True  # edited after the receipt\n")
    result = verify_replay_file(str(path))
    assert result.replay_verified is False
    assert MismatchKind.SHA256_DRIFT in _kinds(result)
    assert MismatchKind.AUDIT_KEY_MISMATCH in _kinds(result)


def test_missing_test_file_fails_closed(tmp_path):
    receipt, tf = _pass_receipt(tmp_path)
    path = _write(tmp_path, receipt)
    tf.unlink()
    result = verify_replay_file(str(path))
    assert result.replay_verified is False
    assert MismatchKind.MISSING_TEST_FILE in _kinds(result)


def test_tampered_verdict_fails_closed(tmp_path):
    receipt, _ = _pass_receipt(tmp_path)
    data = receipt.to_dict()
    data["verdict"] = "FAIL"  # flip PASS -> FAIL but leave exit_code == 0
    # checkout=target so the (unchanged) sha still matches; isolate the verdict check.
    result = verify_replay(data, checkout=receipt.target)
    assert result.replay_verified is False
    assert MismatchKind.VERDICT_INCONSISTENT in _kinds(result)
    assert result.recomputed_verdict == "PASS"


def test_tampered_error_flag_fails_closed(tmp_path):
    # verdict=PASS but an error string present -> error implies ERROR, inconsistent.
    receipt, _ = _pass_receipt(tmp_path)
    data = receipt.to_dict()
    data["error"] = "forged outage"
    result = verify_replay(data, checkout=receipt.target)
    assert result.replay_verified is False
    assert MismatchKind.VERDICT_INCONSISTENT in _kinds(result)


def test_unreadable_receipt_fails_closed(tmp_path):
    result = verify_replay_file(str(tmp_path / "does_not_exist.json"))
    assert result.replay_verified is False
    assert MismatchKind.UNREADABLE_RECEIPT in _kinds(result)


def test_invalid_json_fails_closed(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ this is not json ]")
    result = verify_replay_file(str(p))
    assert result.replay_verified is False
    assert MismatchKind.UNREADABLE_RECEIPT in _kinds(result)


def test_non_object_receipt_fails_closed(tmp_path):
    p = tmp_path / "arr.json"
    p.write_text("[1, 2, 3]")
    result = verify_replay_file(str(p))
    assert result.replay_verified is False
    assert MismatchKind.MALFORMED_RECEIPT in _kinds(result)


def test_unsupported_schema_version_fails_closed(tmp_path):
    receipt, _ = _pass_receipt(tmp_path)
    data = receipt.to_dict()
    data["schema_version"] = "apt-engine/gate-receipt/v99"
    result = verify_replay(data)
    assert result.replay_verified is False
    assert MismatchKind.UNSUPPORTED_SCHEMA in _kinds(result)


def test_missing_required_field_fails_closed(tmp_path):
    receipt, _ = _pass_receipt(tmp_path)
    data = receipt.to_dict()
    del data["pytest_exit_code"]
    result = verify_replay(data)
    assert result.replay_verified is False
    assert MismatchKind.MALFORMED_RECEIPT in _kinds(result)


def test_bool_exit_code_is_rejected(tmp_path):
    # bool is an int subclass; a `true` must not masquerade as an exit code.
    receipt, _ = _pass_receipt(tmp_path)
    data = receipt.to_dict()
    data["pytest_exit_code"] = True
    result = verify_replay(data)
    assert result.replay_verified is False
    assert MismatchKind.MALFORMED_RECEIPT in _kinds(result)


# --- CLI process-boundary exit codes --------------------------------------- #


def test_cli_verify_exit_codes(tmp_path, capsys):
    from apt_engine.cli import main

    # produce a receipt via the gate CLI, then replay-verify it end to end.
    tf = tmp_path / "test_ok.py"
    tf.write_text("def test_ok():\n    assert True\n")
    man = tmp_path / "m.json"
    man.write_text(
        json.dumps(
            {"SCW->MetaReview": {"required": [{"node_id": "test_ok.py::test_ok",
                                               "sha256": _sha(tf)}]}}
        )
    )
    receipt_path = tmp_path / "receipt.json"
    rc = main(
        ["gate", "SCW", "MetaReview", "--measure", str(tmp_path),
         "--impact-manifest", str(man), "--receipt-out", str(receipt_path)]
    )
    capsys.readouterr()
    assert rc == 0

    rc = main(["verify", "--replay", str(receipt_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["replay_verified"] is True

    # tamper the on-disk test -> replay must exit nonzero (fail-closed).
    tf.write_text("def test_ok():\n    assert True  # tampered\n")
    rc = main(["verify", "--replay", str(receipt_path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["replay_verified"] is False


def test_cli_verify_missing_receipt_exits_nonzero(tmp_path, capsys):
    from apt_engine.cli import main

    rc = main(["verify", "--replay", str(tmp_path / "nope.json")])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["replay_verified"] is False


def test_cli_verify_requires_replay_arg(capsys):
    from apt_engine.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["verify"])  # --replay is required
    assert exc.value.code == 2  # argparse usage error


# --- refutation #1: a mistyped `target` must fail closed, not crash ---------- #


@pytest.mark.parametrize("bad_target", [12345, ["a", "b"], {"x": 1}, 1.5])
def test_non_string_target_fails_closed_not_crash(tmp_path, bad_target):
    # `target` is joined into a Path (`_base_dir`); a non-string value must be a
    # typed MALFORMED_RECEIPT, never an unhandled TypeError out of the verifier.
    receipt, _ = _pass_receipt(tmp_path)
    data = receipt.to_dict()
    data["target"] = bad_target
    result = verify_replay(data)  # must NOT raise
    assert result.replay_verified is False
    assert MismatchKind.MALFORMED_RECEIPT in _kinds(result)


def test_null_target_is_allowed(tmp_path):
    # target is optional: an explicit null is fine (defaults to '.'); with a checkout
    # override the (unchanged) file still resolves and the receipt still replays.
    receipt, _ = _pass_receipt(tmp_path)
    data = receipt.to_dict()
    data["target"] = None
    result = verify_replay(data, checkout=receipt.target)
    assert result.replay_verified is True


def test_cli_verify_non_string_target_prints_json_and_exits_1(tmp_path, capsys):
    # end-to-end through the CLI: a poisoned receipt must print a typed JSON result
    # and exit 1 (fail-closed), NOT dump a traceback.
    from apt_engine.cli import main

    receipt, _ = _pass_receipt(tmp_path)
    data = receipt.to_dict()
    data["target"] = 12345  # non-string -> would TypeError in Path() if unguarded
    poisoned = tmp_path / "poisoned.json"
    poisoned.write_text(json.dumps(data))
    rc = main(["verify", "--replay", str(poisoned)])
    out = json.loads(capsys.readouterr().out)  # JSON, not a traceback
    assert rc == 1 and out["replay_verified"] is False
    assert any(m["kind"] == MismatchKind.MALFORMED_RECEIPT.value for m in out["mismatches"])


# --- refutation #2: verdict-consistency guard fires on exit-code-pinned tampers # --


def test_exit_nonzero_tampered_to_pass_fails_closed(tmp_path):
    # a genuine exit-nonzero FAIL forged to PASS: PASS is not producible at a nonzero
    # exit code, so the guard fires (this is the FAIL<->PASS case it DOES catch).
    receipt = _fail_receipt(tmp_path)
    data = receipt.to_dict()
    data["verdict"] = "PASS"
    result = verify_replay(data, checkout=receipt.target)
    assert result.replay_verified is False
    assert MismatchKind.VERDICT_INCONSISTENT in _kinds(result)


def test_error_verdict_without_error_field_fails_closed(tmp_path):
    # an ERROR verdict is only producible with a recorded error; strip the error but
    # keep verdict=ERROR -> ERROR is outside the consistent set -> inconsistent.
    _, receipt = evaluate_measured_mandated_from_with_receipt(
        "SCW", "MetaReview", target=str(tmp_path),
        source=FileManifestSource(str(tmp_path / "missing.json")),
    )
    assert receipt.verdict == "ERROR"
    data = receipt.to_dict()
    data["error"] = None  # drop the outage marker but keep the ERROR verdict
    result = verify_replay(data, checkout=receipt.target)
    assert result.replay_verified is False
    assert MismatchKind.VERDICT_INCONSISTENT in _kinds(result)


def test_non_adjacent_transition_not_fail_fails_closed(tmp_path):
    # forge the destination to a non-adjacent phase but keep PASS: a non-adjacent
    # transition can only be FAIL, so PASS is inconsistent (phase-structural check).
    receipt, _ = _pass_receipt(tmp_path)
    data = receipt.to_dict()
    data["to_phase"] = "SP"  # SCW's only adjacent successor is MetaReview
    result = verify_replay(data, checkout=receipt.target)
    assert result.replay_verified is False
    assert MismatchKind.VERDICT_INCONSISTENT in _kinds(result)


# --- refutation #2: DOCUMENTED SCOPE — flag-swap at a fixed exit code is not caught #


@pytest.mark.parametrize("swapped", ["SKIP", "CONDITIONAL"])
def test_pass_to_skip_or_conditional_at_exit0_is_documented_scope_limit(tmp_path, swapped):
    # SCOPED GUARANTEE (module docstring / README): the skip/conditional caller flags
    # are NOT on a v1 receipt, so PASS vs SKIP vs CONDITIONAL at exit 0 are genuinely
    # indistinguishable. This pins that documented limitation: the swap replays
    # verified (it is not a FAIL<->PASS inconsistency), so no claim of catching it.
    receipt, _ = _pass_receipt(tmp_path)
    data = receipt.to_dict()
    data["verdict"] = swapped  # exit_code stays 0
    result = verify_replay(data, checkout=receipt.target)
    assert result.replay_verified is True
    assert MismatchKind.VERDICT_INCONSISTENT not in _kinds(result)
