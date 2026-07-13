"""MCP frontend — tool bodies are pure and testable without fastmcp installed."""

from apt_engine.frontends.mcp_server import build_tools
from apt_engine.phases import CHAIN


def test_all_tools_present():
    tools = build_tools()
    assert set(tools) == {
        "apt_chain",
        "apt_detect",
        "apt_gate",
        "apt_gate_measured",
        "apt_reconcile",
        "apt_legion",
    }


def test_gate_measured_tool_maps_exit_code(monkeypatch):
    # The measured tool runs real pytest via pytest_runner; here we patch the
    # runner to prove it maps exit code -> verdict (no caller bool involved).
    import apt_engine.precondition as pre

    gate_m = build_tools()["apt_gate_measured"]
    monkeypatch.setattr(pre, "pytest_runner", lambda target: 0)
    assert gate_m("SCW", "MetaReview", "impact")["verdict"] == "PASS"
    monkeypatch.setattr(pre, "pytest_runner", lambda target: 1)
    assert gate_m("SCW", "MetaReview", "impact")["verdict"] == "FAIL"


def test_gate_measured_tool_serializes_unevaluable_manifest_as_error(tmp_path):
    result = build_tools()["apt_gate_measured"](
        "SCW", "MetaReview", str(tmp_path), str(tmp_path / "missing.json")
    )

    assert result["verdict"] == "ERROR"
    assert result["receipt"]["verdict"] == "ERROR"
    assert result["receipt"]["error"]


def test_chain_tool_returns_canonical_order():
    rows = build_tools()["apt_chain"]()
    assert [r["name"] for r in rows] == list(CHAIN)


def test_gate_tool_matches_core_semantics():
    gate = build_tools()["apt_gate"]
    # Fail-closed: the precondition must be explicitly asserted to PASS; an
    # unstated precondition is never a silent PASS (frontier #3 fix).
    assert gate("SA", "SP", precondition_met=True)["verdict"] == "PASS"
    assert gate("SA", "SP")["verdict"] != "PASS"
    assert gate("SP", "ST", skipped=True)["verdict"] == "SKIP"
    assert (
        gate("ST", "SCW", precondition_met=False)["gate_version"] == "v27_phase_scw_dispatch_guard"
    )


def test_reconcile_tool_both_directions():
    rec = build_tools()["apt_reconcile"]
    assert rec("v9_PH6_Feedback")["v27"] == ["MetaReview", "Cleanup"]
    assert rec("SA")["v9"] == ["v9_PH1_SA", "v9_PH2_Root"]
    assert set(rec()["v9_to_v27"]) == {
        "v9_PH1_SA",
        "v9_PH2_Root",
        "v9_PH3_SP",
        "v9_PH4_ST",
        "v9_PH5_SCW",
        "v9_PH6_Feedback",
    }


def test_legion_tool_reports_hades_realize_table():
    leg = build_tools()["apt_legion"]()
    assert leg["verdict_commander"] == "naesengmoon"
    table = leg["hades_realizes_by_verdict"]
    # Every verdict state, incl. ERROR (could-not-evaluate); only PASS realizes.
    assert table == {
        "PASS": True,
        "FAIL": False,
        "SKIP": False,
        "CONDITIONAL": False,
        "ERROR": False,
    }
    assert len(leg["roster"]) == 7
