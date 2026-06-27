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


def _manifest(tmp_path):
    import json

    man = tmp_path / "apt-impact.json"
    man.write_text(json.dumps({"SCW->MetaReview": {"required": ["impact"]}}))
    return str(man)


def test_mandated_rejects_unrelated_passing_dir(capsys, tmp_path):
    # H-C: an unrelated passing dir does NOT satisfy the mandated precondition.
    (tmp_path / "test_unrelated.py").write_text("def test_ok():\n    assert True\n")
    rc, out = _run(
        capsys,
        ["gate", "SCW", "MetaReview", "--measure", str(tmp_path), "--impact-manifest", _manifest(tmp_path)],
    )
    assert rc == 1 and out["verdict"] == "FAIL"


def test_mandated_accepts_real_impact_test(capsys, tmp_path):
    # a real, passing MANDATED impact test (node id matches 'impact') unlocks it.
    (tmp_path / "test_scw_impact.py").write_text("def test_scw_impact():\n    assert True\n")
    rc, out = _run(
        capsys,
        ["gate", "SCW", "MetaReview", "--measure", str(tmp_path), "--impact-manifest", _manifest(tmp_path)],
    )
    assert rc == 0 and out["verdict"] == "PASS"
