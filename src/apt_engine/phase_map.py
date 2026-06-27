"""(a) v9 ↔ v27 APT phase-taxonomy reconciliation.

The consumer KG carries an older **v9** phase decomposition as `:AptPhase` nodes:

    v9_PH1_SA        SemanticAnchor 정렬
    v9_PH2_Root      RootIntentSpan 확정
    v9_PH3_SP        SemanticPyramid 재귀 하강
    v9_PH4_ST        SemanticTwin 결정화
    v9_PH5_SCW       SourceCodeWorld 구현
    v9_PH6_Feedback  KG/Runtime 피드백

apt-engine implements the **v27** phase-contract (`phases.py`):

    SA → SP → ST → SCW → MetaReview → Cleanup

These are not 1:1. This module is the SINGLE reconciliation map, so the two
taxonomies can never silently disagree:

  - v9 PH1 (SA) and PH2 (RootIntentSpan) both fold into v27 **SA** — in v27 the
    root span is SA's `:HAS_ROOT` postcondition, not a separate phase.
  - PH3→SP, PH4→ST, PH5→SCW are clean 1:1.
  - v9 PH6 (Feedback) fans out to v27 **MetaReview + Cleanup** — v27 splits the
    single feedback phase into the adversarial review (Phase 5) and the ratchet
    sweep (Phase 6).

Invariants enforced by `tests/test_phase_map.py` (revert-proof):
  - TOTAL: every v9 phase maps to ≥1 v27 phase.
  - ONTO:  every v27 phase is the image of ≥1 v9 phase (no orphan v27 phase).
  - CLOSED: every mapped v27 name is a real member of `phases.CHAIN`.
"""

from __future__ import annotations

from .phases import CHAIN

__all__ = ["V9_PHASES", "V9_TO_V27", "to_v27", "to_v9", "is_total", "is_onto", "orphans"]

# Canonical v9 phase node names in the KG (the clean `v9_PHx_*` set).
V9_PHASES: tuple[str, ...] = (
    "v9_PH1_SA",
    "v9_PH2_Root",
    "v9_PH3_SP",
    "v9_PH4_ST",
    "v9_PH5_SCW",
    "v9_PH6_Feedback",
)

# v9 phase -> the v27 phase name(s) it reconciles to.
V9_TO_V27: dict[str, tuple[str, ...]] = {
    "v9_PH1_SA": ("SA",),
    "v9_PH2_Root": ("SA",),  # RootIntentSpan = SA's HAS_ROOT postcondition
    "v9_PH3_SP": ("SP",),
    "v9_PH4_ST": ("ST",),
    "v9_PH5_SCW": ("SCW",),
    "v9_PH6_Feedback": ("MetaReview", "Cleanup"),  # v27 splits feedback in two
}


def to_v27(v9_phase: str) -> tuple[str, ...]:
    """The v27 phase(s) a v9 phase reconciles to."""
    try:
        return V9_TO_V27[v9_phase]
    except KeyError as exc:
        raise KeyError(f"unknown v9 phase: {v9_phase!r}; valid: {V9_PHASES}") from exc


def to_v9(v27_phase: str) -> tuple[str, ...]:
    """The v9 phase(s) that reconcile to a given v27 phase (inverse image)."""
    if v27_phase not in CHAIN:
        raise KeyError(f"unknown v27 phase: {v27_phase!r}; valid: {CHAIN}")
    return tuple(v9 for v9, v27s in V9_TO_V27.items() if v27_phase in v27s)


def is_total() -> bool:
    """Every v9 phase has a non-empty v27 image."""
    return all(V9_TO_V27.get(p) for p in V9_PHASES)


def is_onto() -> bool:
    """Every v27 phase is reached by at least one v9 phase."""
    return not orphans()


def orphans() -> tuple[str, ...]:
    """v27 phases that no v9 phase maps to (should be empty)."""
    reached = {v27 for v27s in V9_TO_V27.values() for v27 in v27s}
    return tuple(p for p in CHAIN if p not in reached)
