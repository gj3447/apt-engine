"""CLI `gate` exit-code contract + measured path (H-A / H-B fix-forward).

The deep-think red-team found the "fail-closed frontend" only changed the JSON
output, not the process exit status — so `apt-engine gate ... && deploy` ran on a
blocking FAIL. These tests pin: exit 0 iff PASS, and the production `--measure`
path gating on a REAL pytest run.
"""

import json

from apt_engine.cli import main


def _run(capsys, argv):
    rc = main(argv)
    out = json.loads(capsys.readouterr().out)
    return rc, out


def test_unstated_precondition_exits_nonzero(capsys):
    rc, out = _run(capsys, ["gate", "SA", "SP"])
    assert rc == 1 and out["verdict"] != "PASS"


def test_asserted_precondition_pass_exits_zero(capsys):
    rc, out = _run(capsys, ["gate", "SA", "SP", "--precondition-met"])
    assert rc == 0 and out["verdict"] == "PASS"


def test_skip_exits_nonzero(capsys):
    # SKIP != advance: must not exit 0 (else `&&`/set -e treat a skip as success).
    rc, out = _run(capsys, ["gate", "SP", "ST", "--skip"])
    assert rc == 1 and out["verdict"] == "SKIP"


def test_fail_exits_nonzero(capsys):
    rc, out = _run(capsys, ["gate", "SA", "SCW"])  # non-adjacent -> FAIL
    assert rc == 1 and out["verdict"] == "FAIL"


def test_measured_passing_target_exits_zero(capsys, tmp_path):
    # production measured path: a REAL passing pytest run unlocks the transition.
    (tmp_path / "test_green.py").write_text("def test_ok():\n    assert True\n")
    rc, out = _run(capsys, ["gate", "SCW", "MetaReview", "--measure", str(tmp_path)])
    assert rc == 0 and out["verdict"] == "PASS"


def test_measured_failing_target_exits_nonzero(capsys, tmp_path):
    # a REAL failing pytest run blocks it (fail-closed end-to-end, exit nonzero).
    (tmp_path / "test_red.py").write_text("def test_no():\n    assert False\n")
    rc, out = _run(capsys, ["gate", "SCW", "MetaReview", "--measure", str(tmp_path)])
    assert rc == 1 and out["verdict"] == "FAIL"


def test_mandated_rejects_unrelated_dir(capsys, tmp_path):
    # H-C: a dir lacking the EXACT mandated node id does not satisfy it.
    import json

    (tmp_path / "test_unrelated.py").write_text("def test_ok():\n    assert True\n")
    man = tmp_path / "apt-impact.json"
    man.write_text(json.dumps({"SCW->MetaReview": {"required": ["test_scw.py::test_contract"]}}))
    rc, out = _run(
        capsys, ["gate", "SCW", "MetaReview", "--measure", str(tmp_path), "--impact-manifest", str(man)],
    )
    assert rc == 1 and out["verdict"] == "FAIL"


def test_mandated_accepts_sha_pinned_test(capsys, tmp_path):
    # the EXACT, sha-pinned mandated test present + passing unlocks it.
    import hashlib
    import json

    tf = tmp_path / "test_scw_impact.py"
    tf.write_text("def test_contract():\n    assert True\n")
    sha = hashlib.sha256(tf.read_bytes()).hexdigest()
    man = tmp_path / "apt-impact.json"
    man.write_text(json.dumps({"SCW->MetaReview": {"required": [
        {"node_id": "test_scw_impact.py::test_contract", "sha256": sha}]}}))
    rc, out = _run(
        capsys, ["gate", "SCW", "MetaReview", "--measure", str(tmp_path), "--impact-manifest", str(man)],
    )
    assert rc == 0 and out["verdict"] == "PASS"


def test_mandated_rejects_content_forge(capsys, tmp_path):
    # SAME node id, content differs from the pinned sha -> rejected (HIGH-2 close).
    import hashlib
    import json

    canonical = b"def test_contract():\n    assert True\n"
    (tmp_path / "test_scw_impact.py").write_text("def test_contract():\n    assert True  # forged\n")
    man = tmp_path / "apt-impact.json"
    man.write_text(json.dumps({"SCW->MetaReview": {"required": [
        {"node_id": "test_scw_impact.py::test_contract", "sha256": hashlib.sha256(canonical).hexdigest()}]}}))
    rc, out = _run(
        capsys, ["gate", "SCW", "MetaReview", "--measure", str(tmp_path), "--impact-manifest", str(man)],
    )
    assert rc == 1 and out["verdict"] == "FAIL"


def test_mandated_under_ancestor_pytest_config(capsys, tmp_path):
    # red-team HIGH: the documented `--measure <subdir>` case with a project
    # pytest config at the ROOT must work end-to-end (was crashing/false-reject).
    import hashlib
    import json

    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    sub = tmp_path / "tests" / "impact"
    sub.mkdir(parents=True)
    tf = sub / "test_scw.py"
    tf.write_text("def test_contract():\n    assert True\n")
    man = tmp_path / "apt-impact.json"
    man.write_text(json.dumps({"SCW->MetaReview": {"required": [
        {"node_id": "test_scw.py::test_contract", "sha256": hashlib.sha256(tf.read_bytes()).hexdigest()}]}}))
    rc, out = _run(
        capsys, ["gate", "SCW", "MetaReview", "--measure", str(sub), "--impact-manifest", str(man)],
    )
    assert rc == 0 and out["verdict"] == "PASS"
