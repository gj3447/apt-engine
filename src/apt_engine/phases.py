"""Canonical APT phase chain — the single source of truth.

Transcribed from `bhgman_tool/ADRs/apt-phase-contract-2026-05-25.md`
(KG: adr-apt-phase-contract-2026-05-25, APT_methodology_v27).

APT (v27) is a four-phase cycle SA -> SP -> ST -> SCW, plus an optional
Phase 5 MetaReview and Phase 6 Cleanup. Each transition is gated; gates carry
preconditions and emit a verdict (see `gate.py`).

DRIFT FIX (vs. the `bhgman_tool/engine/.../apt.py` skeleton):
  The skeleton declared APT_PHASES = (SA, SP, ST, SCW, "Cleanup", "MetaReview"),
  ordering Cleanup (Phase 6) *before* MetaReview (Phase 5). The phase-contract
  ADR is explicit: "optional Phase 5 MetaReview + Phase 6 Cleanup", so MetaReview
  precedes Cleanup. This module follows the ADR ordering. `_current_phase`-style
  "latest phase with evidence" logic depends on this order, so the skeleton would
  have reported Cleanup as earlier than MetaReview. apt-engine corrects it here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Phase", "CHAIN", "PHASES", "phase_by_name", "next_phase", "is_self_application"]


@dataclass(frozen=True)
class Phase:
    """One APT phase and the contract it honors.

    Attributes mirror the phase-contract ADR tables: what the phase requires
    coming in, what it must emit going out, and the canonical APT_GATE_VERSION
    string emitted when its incoming gate fails.
    """

    name: str
    number: int  # 1..6 lifecycle position
    title: str
    precondition: str
    postcondition: str
    gate_version_on_fail: str
    optional: bool = False
    # Phases that may never recursively target themselves (max_depth=1).
    self_application_forbidden: bool = False
    aliases: tuple[str, ...] = field(default_factory=tuple)
    # Provenance of this row's contract strings: "adr" = transcribed from the
    # phase-contract ADR; "engine-local" = an engine invention the ADR does not
    # cover (the ADR tables end at MetaReview). Keeps the SSOT honest about its
    # own sources. KG: finding-ooptdd-apt-engine-fix-harness-20260627 (T5).
    provenance: str = "adr"


# Canonical lifecycle order (Phase 1..6). ORDER IS LOAD-BEARING — see DRIFT FIX.
PHASES: tuple[Phase, ...] = (
    Phase(
        name="SA",
        number=1,
        title="SemanticAnchor",
        precondition="Topic + project anchor; no prior phase required.",
        postcondition=":SemanticAnchor node + 5 core fields "
        "(objective/definition/keyAssertion/C_S/contextBudget) + :HAS_ROOT to root Span.",
        gate_version_on_fail="v27_phase_sa_no_topic",
    ),
    Phase(
        name="SP",
        number=2,
        title="SemanticPyramid",
        precondition="SemanticAnchor with 5 core fields populated; gate VR APPROVED.",
        postcondition="Root Span + N-level decomposition with leaves marked :AtomicSpan; "
        "C(S) 5-predicate non-null on every Span.",
        gate_version_on_fail="v27_phase_sp_dispatch_guard",
    ),
    Phase(
        name="ST",
        number=3,
        title="SemanticTwin",
        precondition="All SP leaf spans = AtomicSpan (Crystallization Frontier); gate VR APPROVED.",
        postcondition="Per-AtomicSpan :Contract + :Task + 8 ST Decision Area annotations.",
        gate_version_on_fail="v27_phase_st_dispatch_guard",
    ),
    Phase(
        name="SCW",
        number=4,
        title="SourceCodeWorld",
        precondition="Per-AtomicSpan Contract crystallized + 8 ST Decision Areas covered; "
        "gate VR APPROVED.",
        postcondition="Per-Task :SourceCodeNode + tests (TDAD impact_tests mandatory) + "
        "# KG: ref comments (Longinus L5-L7 forward binding).",
        gate_version_on_fail="v27_phase_scw_dispatch_guard",
    ),
    Phase(
        name="MetaReview",
        number=5,
        title="MetaReview",
        precondition="SCW completion VR + AdversarialChallenge >= 1 (Wave 9 §3 Constrain Layer).",
        postcondition=":Lesson (>=0) + Naesengmoon self-meta VR + :AdversarialChallenge >= 1.",
        gate_version_on_fail="v27_phase_meta_review_dispatch_guard",
        optional=True,
        self_application_forbidden=True,
        aliases=("Meta-Review", "Meta Review"),
    ),
    Phase(
        name="Cleanup",
        number=6,
        title="Cleanup",
        precondition="MetaReview cycle close; ratchet baseline available.",
        postcondition="Ratchet applied; orphans swept; cycle artifacts archived.",
        gate_version_on_fail="v27_phase_cleanup_dispatch_guard",
        optional=True,
        aliases=("Phase 6",),
        # The phase-contract ADR's tables end at MetaReview; Cleanup's precond/
        # postcond/gate_version are an engine convention, not a transcription.
        provenance="engine-local",
    ),
)

# Ordered names — convenience tuple used by the detector and ordering checks.
CHAIN: tuple[str, ...] = tuple(p.name for p in PHASES)

_BY_NAME: dict[str, Phase] = {}
for _p in PHASES:
    _BY_NAME[_p.name.lower()] = _p
    for _a in _p.aliases:
        _BY_NAME[_a.lower()] = _p


def phase_by_name(name: str) -> Phase:
    """Resolve a phase by canonical name or known alias (case-insensitive)."""
    try:
        return _BY_NAME[name.strip().lower()]
    except KeyError as exc:
        raise KeyError(f"unknown APT phase: {name!r}; valid: {CHAIN}") from exc


def next_phase(name: str) -> Phase | None:
    """The phase that follows `name` in canonical order, or None at the end."""
    current = phase_by_name(name)
    idx = current.number  # number is 1-based, PHASES is 0-based
    return PHASES[idx] if idx < len(PHASES) else None


def is_self_application(from_phase: str, to_phase: str) -> bool:
    """True if dispatching `from_phase` -> `to_phase` is a forbidden self-application.

    MetaReview MUST NOT recursively MetaReview itself (max_depth=1, delta=0).
    """
    src = phase_by_name(from_phase)
    dst = phase_by_name(to_phase)
    return src.name == dst.name and dst.self_application_forbidden
