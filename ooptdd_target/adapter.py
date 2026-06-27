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

    Ships 'gate_failed_closed' only when the real verdict is non-PASS (earned by
    the fail-closed default). Returns the observed verdict.
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

    Ships 'precondition_measured_pass' carrying the real verdict. Returns it.
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

    Ships 'precondition_measured_block' carrying the real failing verdict +
    canonical gate_version. Returns the verdict.
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


def run_apt_fix_pipeline(backend, cid: str) -> dict:
    """Loop entry point: exercise the two fixes under ``cid``, shipping earned events."""
    return {
        "failclosed_verdict": emit_failclosed_phase(backend, cid),
        "measured_pass_verdict": emit_measured_pass_phase(backend, cid),
        "measured_block_verdict": emit_measured_block_phase(backend, cid),
    }
