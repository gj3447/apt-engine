"""MCP frontend for apt-engine.

Exposes the stdlib-only core as MCP tools. The tool *bodies* are pure functions
returned by `build_tools()` — they have no fastmcp dependency, so they are unit
testable without the optional `mcp` extra installed. `register(mcp)` / `main()`
wrap them onto a FastMCP server (imported lazily; only needed at serve time).

    pip install -e '.[mcp]'
    python -m apt_engine.frontends.mcp_server      # stdio MCP server

Tools: apt_chain, apt_detect, apt_gate, apt_reconcile, apt_legion.
"""

from __future__ import annotations

from typing import Any, Callable

from ..detect import detect_phase
from ..gate import Verdict, evaluate_transition
from ..legion import COMMANDERS, KG_CANONICAL_NODE, hades_realizes
from ..phase_map import V9_TO_V27, to_v9, to_v27
from ..phases import PHASES


def _chain() -> list[dict[str, Any]]:
    return [
        {"number": p.number, "name": p.name, "title": p.title, "optional": p.optional,
         "precondition": p.precondition, "postcondition": p.postcondition,
         "gate_version_on_fail": p.gate_version_on_fail}
        for p in PHASES
    ]


def _detect(repo_path: str) -> dict[str, Any]:
    return detect_phase(repo_path)


def _gate(from_phase: str, to_phase: str, precondition_met: bool = True,
          conditional: bool = False, skipped: bool = False) -> dict[str, Any]:
    r = evaluate_transition(from_phase, to_phase, precondition_met=precondition_met,
                            conditional=conditional, skipped=skipped)
    return {"from_phase": r.from_phase, "to_phase": r.to_phase, "verdict": r.verdict.value,
            "reason": r.reason, "gate_version": r.gate_version}


def _reconcile(phase: str | None = None) -> dict[str, Any]:
    """Full v9<->v27 map, or one phase's image in both directions."""
    if phase is None:
        return {"v9_to_v27": {k: list(v) for k, v in V9_TO_V27.items()}}
    if phase in V9_TO_V27:
        return {"scheme": "v9", "phase": phase, "v27": list(to_v27(phase))}
    return {"scheme": "v27", "phase": phase, "v9": list(to_v9(phase))}


def _legion() -> dict[str, Any]:
    return {
        "roster": [
            {"name": c.name, "verb_ko": c.verb_ko, "verb_en": c.verb_en,
             "requires": list(c.requires), "provides": list(c.provides),
             "is_stage": c.is_stage, "kg_node": KG_CANONICAL_NODE[c.name]}
            for c in COMMANDERS
        ],
        "verdict_commander": "naesengmoon",
        "realize_commander": "hades",
        "hades_realizes_by_verdict": {
            v: hades_realizes(Verdict[v]) for v in ("PASS", "FAIL", "SKIP", "CONDITIONAL")
        },
    }


def build_tools() -> dict[str, Callable[..., Any]]:
    """Pure tool callables, keyed by MCP tool name. fastmcp-free (unit testable)."""
    return {
        "apt_chain": _chain,
        "apt_detect": _detect,
        "apt_gate": _gate,
        "apt_reconcile": _reconcile,
        "apt_legion": _legion,
    }


def register(mcp: Any) -> None:
    """Attach every tool in build_tools() to a FastMCP instance."""
    for name, fn in build_tools().items():
        mcp.tool(name=name)(fn)


def main() -> int:
    try:
        from fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - serve-time only
        raise SystemExit("apt-engine MCP frontend needs the 'mcp' extra: pip install -e '.[mcp]'") from exc
    mcp = FastMCP("apt-engine")
    register(mcp)
    mcp.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
