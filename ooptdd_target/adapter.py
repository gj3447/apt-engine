"""ooptdd-loop in_process target — binds APT fix trace gates to REAL apt_engine code.

Every event shipped here is EARNED by genuinely running the fixed engine:
  - gate_failed_closed         : the real MCP ``apt_gate`` frontend, called with the
                                 precondition UNSTATED, returns a non-PASS verdict.
                                 With the old fail-open default the verdict was PASS
                                 and this event would NOT ship -> gate stays RED
                                 (this is exactly the revert-proof seam).
  - precondition_measured_pass : ``evaluate_measured`` run against a REAL passing
                                 pytest process (exit 0) -> PASS.
  - precondition_measured_block: ``evaluate_measured`` run against a REAL failing
                                 pytest process (exit 1) -> FAIL.

Longinus binding: each must_emit literal appears verbatim as a string constant in
the body of its bound symbol below (AST-checked by ooptdd_loop.longinus). Rename a
literal and the gate goes UNBOUND.

Load-bearing OOPTDD rule (per the sibling applications): event-name literals live
ONLY in this adapter, never in apt_engine/* — the engine stays trace-free; the
adapter is the instrumentation seam.

# KG: finding-ooptdd-apt-engine-fix-harness-20260627
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# src-layout bootstrap: make ``apt_engine`` importable regardless of who launches
# the loop (CLI from repo root, or the MCP server from its own cwd).
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from apt_engine.frontends.mcp_server import build_tools  # noqa: E402
from apt_engine.precondition import evaluate_measured  # noqa: E402

_SERVICE = "apt-engine-fix-harness"
_KG_ANCHOR = "finding-ooptdd-apt-engine-fix-harness-20260627"


def _ev(cid: str, event: str, **attrs) -> dict:
    """Shape one trace event the way the memory backend keys + counts it (cid + event)."""
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": _SERVICE,
        "event": event,
        **attrs,
    }


def _real_pytest(target: str) -> int:
    """Run pytest over ``target`` in an isolated subprocess; return its REAL exit code.

    A genuine pytest collection+run — not a stubbed bool. Hermetic: plugin
    autoload is OFF so the inner run can't ship traces or inherit apt-engine's
    own pytest ini; ``target`` is a fresh tempdir so collection is just our file.
    """
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", target],
        capture_output=True,
        env=env,
    )
    return completed.returncode


def emit_failclosed_phase(backend, cid: str) -> str:
    """Real MCP ``apt_gate`` with the precondition UNSTATED must NOT be PASS.

    Ships the fail-closed event only when the real verdict is non-PASS (earned by
    the fail-closed default). The event-name literal lives ONLY in the ship() call
    below, so renaming it really does flip the Longinus binding to UNBOUND.
    """
    apt_gate = build_tools()["apt_gate"]
    verdict = apt_gate("SA", "SP")["verdict"]  # precondition deliberately not asserted
    if verdict != "PASS":
        backend.ship([
            _ev(cid, "gate_failed_closed", observed_verdict=verdict,
                transition="SA->SP", precondition="unstated", kg_anchor=_KG_ANCHOR)
        ])
    return verdict


def emit_measured_pass_phase(backend, cid: str) -> str:
    """Real PASSING pytest (exit 0) -> measured SCW->MetaReview PASS.

    Ships the measured-pass event carrying the real verdict (literal only in the
    ship() call below). Returns the verdict.
    """
    with tempfile.TemporaryDirectory() as d:
        Path(d, "test_impact_green.py").write_text("def test_ok():\n    assert True\n")
        result = evaluate_measured("SCW", "MetaReview", runner=_real_pytest, target=d)
    if result.verdict.value == "PASS":
        backend.ship([
            _ev(cid, "precondition_measured_pass", verdict=result.verdict.value,
                transition="SCW->MetaReview", kg_anchor=_KG_ANCHOR)
        ])
    return result.verdict.value


def emit_measured_block_phase(backend, cid: str) -> str:
    """Real FAILING pytest (exit 1) -> measured SCW->MetaReview FAIL (block).

    Ships the measured-block event carrying the real failing verdict + canonical
    gate_version (literal only in the ship() call below). Returns the verdict.
    """
    with tempfile.TemporaryDirectory() as d:
        Path(d, "test_impact_red.py").write_text("def test_no():\n    assert False\n")
        result = evaluate_measured("SCW", "MetaReview", runner=_real_pytest, target=d)
    if result.verdict.value == "FAIL":
        backend.ship([
            _ev(cid, "precondition_measured_block", verdict=result.verdict.value,
                gate_version=result.gate_version, transition="SCW->MetaReview",
                kg_anchor=_KG_ANCHOR)
        ])
    return result.verdict.value


def emit_cli_measured_phase(backend, cid: str) -> int:
    """Run the REAL production CLI measured gate on a failing target.

    Proves the WIRED production path (frontier #1, red-team H-B): `apt-engine gate
    SCW MetaReview --measure <dir>` over a failing pytest must exit NONZERO and
    report FAIL. Ships the cli-measured-block event only when the production CLI
    genuinely blocks (exit != 0 AND verdict FAIL). Returns the observed exit code.
    """
    from apt_engine.cli import main

    with tempfile.TemporaryDirectory() as d:
        Path(d, "test_impact_red.py").write_text("def test_no():\n    assert False\n")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["gate", "SCW", "MetaReview", "--measure", d])
    out = json.loads(buf.getvalue())
    if rc != 0 and out["verdict"] == "FAIL":
        backend.ship([
            _ev(cid, "cli_measured_block", exit_code=rc, verdict=out["verdict"],
                transition="SCW->MetaReview", kg_anchor=_KG_ANCHOR)
        ])
    return rc


def emit_forge_rejected_phase(backend, cid: str) -> str:
    """The MANDATED gate REJECTS an unrelated passing dir as a GENUINE forge.

    Uses the real production collector+runner and ships only when the evidence is
    a true forge-rejection — met False AND exit_code 5 (no mandated test
    collected), NOT merely any FAIL. So a deny-all regression (which would also
    FAIL) cannot masquerade as a rejection here (red-team MED-3). Returns a
    met/exit summary.
    """
    from apt_engine.precondition import (
        ImpactReq,
        measure_mandated,
        pytest_collector,
        pytest_id_runner,
    )

    with tempfile.TemporaryDirectory() as d:
        Path(d, "test_unrelated.py").write_text("def test_ok():\n    assert True\n")
        evidence = measure_mandated(
            d, (ImpactReq("test_scw.py::test_contract"),),
            collector=pytest_collector, runner=pytest_id_runner)
    if evidence.met is False and evidence.exit_code == 5:
        backend.ship([
            _ev(cid, "mandated_forge_rejected", exit_code=evidence.exit_code,
                source=evidence.source, transition="SCW->MetaReview", kg_anchor=_KG_ANCHOR)
        ])
    return f"met={evidence.met} exit={evidence.exit_code}"


def emit_content_forge_rejected_phase(backend, cid: str) -> str:
    """The MANDATED gate REJECTS a same-named test whose CONTENT differs from the
    pinned sha256 (the HIGH-2 content-forge close).

    Writes a test at the exact mandated node id but with FORGED content, pins the
    CANONICAL content's sha, and ships only on a true content-forge (met False AND
    exit_code 6 = sha mismatch). Returns a met/exit summary.
    """
    import hashlib

    from apt_engine.precondition import (
        ImpactReq,
        measure_mandated,
        pytest_collector,
        pytest_id_runner,
    )

    canonical = b"def test_contract():\n    assert True\n"
    with tempfile.TemporaryDirectory() as d:
        Path(d, "test_scw_impact.py").write_text("def test_contract():\n    assert True  # forged\n")
        req = ImpactReq("test_scw_impact.py::test_contract", hashlib.sha256(canonical).hexdigest())
        evidence = measure_mandated(d, (req,), collector=pytest_collector, runner=pytest_id_runner)
    if evidence.met is False and evidence.exit_code == 6:
        backend.ship([
            _ev(cid, "content_forge_rejected", exit_code=evidence.exit_code,
                source=evidence.source, transition="SCW->MetaReview", kg_anchor=_KG_ANCHOR)
        ])
    return f"met={evidence.met} exit={evidence.exit_code}"


def emit_mandated_accepts_phase(backend, cid: str) -> str:
    """The MANDATED gate ACCEPTS the exact, sha-pinned mandated test passing.

    Positive-path sibling of the forge gates (red-team MED-3): together they pin
    genuine-pass -> PASS AND forge -> FAIL, so neither an allow-all nor a deny-all
    regression can keep all gates GREEN. Returns the observed verdict.
    """
    import hashlib

    from apt_engine.precondition import evaluate_measured_mandated_default

    with tempfile.TemporaryDirectory() as d:
        tf = Path(d, "test_scw_impact.py")
        tf.write_text("def test_contract():\n    assert True\n")
        manifest = Path(d, "apt-impact.json")
        manifest.write_text(json.dumps({"SCW->MetaReview": {"required": [
            {"node_id": "test_scw_impact.py::test_contract",
             "sha256": hashlib.sha256(tf.read_bytes()).hexdigest()}]}}))
        result = evaluate_measured_mandated_default(
            "SCW", "MetaReview", target=d, manifest_path=str(manifest))
    if result.verdict.value == "PASS":
        backend.ship([
            _ev(cid, "mandated_accepts", verdict=result.verdict.value,
                transition="SCW->MetaReview", kg_anchor=_KG_ANCHOR)
        ])
    return result.verdict.value


def run_apt_fix_pipeline(backend, cid: str) -> dict:
    """Loop entry point: exercise the fixes under ``cid``, shipping earned events."""
    return {
        "failclosed_verdict": emit_failclosed_phase(backend, cid),
        "measured_pass_verdict": emit_measured_pass_phase(backend, cid),
        "measured_block_verdict": emit_measured_block_phase(backend, cid),
        "cli_measured_exit": emit_cli_measured_phase(backend, cid),
        "forge_rejected_summary": emit_forge_rejected_phase(backend, cid),
        "content_forge_rejected_summary": emit_content_forge_rejected_phase(backend, cid),
        "mandated_accepts_verdict": emit_mandated_accepts_phase(backend, cid),
    }
