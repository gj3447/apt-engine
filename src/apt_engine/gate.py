"""APT gate verdict model.

Transcribed from `bhgman_tool/ADRs/apt-gate-semantics-2026-05-25.md`
(KG: adr-apt-gate-semantics-2026-05-25).

A gate evaluates whether a phase transition is permitted. Verdict states are
PASS | FAIL | SKIP | CONDITIONAL. Load-bearing rule (remediation of
taliban-blocker-C9-01-2026-05-13): **SKIP is never counted as PASS.** A
CONDITIONAL verdict requires a follow-up VR before the downstream phase unlocks.

This module is the authoritative-verdict shape; it does NOT implement the
KG-backed precondition resolver (that runtime lives in SYMPOSIUM/dgx per
adr-apt-dgx-runtime-delegation-2026-05-25). Here we model the verdict algebra
and the advance decision so tool-layer callers share one definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .phases import Phase, is_self_application, next_phase, phase_by_name

__all__ = ["Verdict", "GateResult", "can_advance", "evaluate_transition"]


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    CONDITIONAL = "CONDITIONAL"

    @property
    def unlocks_downstream(self) -> bool:
        """Only PASS unlocks the next phase. SKIP != PASS; CONDITIONAL needs follow-up."""
        return self is Verdict.PASS


@dataclass(frozen=True)
class GateResult:
    from_phase: str
    to_phase: str
    verdict: Verdict
    reason: str
    gate_version: str | None = None  # canonical APT_GATE_VERSION on FAIL


def can_advance(verdict: Verdict) -> bool:
    """Whether a verdict permits unlocking the downstream phase.

    SKIP is explicitly NOT an advance — that is the whole point of the separate
    counter mandated by the gate-semantics ADR.
    """
    return verdict.unlocks_downstream


def evaluate_transition(
    from_phase: str,
    to_phase: str,
    *,
    precondition_met: bool,
    conditional: bool = False,
    skipped: bool = False,
) -> GateResult:
    """Produce a GateResult for a requested phase transition.

    Order of precedence:
      1. Forbidden self-application (MetaReview -> MetaReview) -> FAIL.
      2. Out-of-order / non-adjacent transition -> FAIL.
      3. Explicit skip -> SKIP (never PASS).
      4. Precondition unmet -> FAIL with the destination's gate_version.
      5. Conditional pass -> CONDITIONAL.
      6. Otherwise -> PASS.
    """
    src: Phase = phase_by_name(from_phase)
    dst: Phase = phase_by_name(to_phase)

    if is_self_application(from_phase, to_phase):
        return GateResult(
            src.name,
            dst.name,
            Verdict.FAIL,
            "self_application_forbidden (max_depth=1, delta=0)",
            dst.gate_version_on_fail,
        )

    expected = next_phase(src.name)
    if expected is None or expected.name != dst.name:
        return GateResult(
            src.name,
            dst.name,
            Verdict.FAIL,
            f"non-adjacent transition; {src.name} must advance to "
            f"{expected.name if expected else '(terminal)'}",
            dst.gate_version_on_fail,
        )

    if skipped:
        return GateResult(
            src.name, dst.name, Verdict.SKIP, "phase skipped (counted separately, != PASS)"
        )

    if not precondition_met:
        return GateResult(
            src.name,
            dst.name,
            Verdict.FAIL,
            f"precondition unmet: {dst.precondition}",
            dst.gate_version_on_fail,
        )

    if conditional:
        return GateResult(
            src.name,
            dst.name,
            Verdict.CONDITIONAL,
            "precondition partially met; follow-up VR required before unlock",
        )

    return GateResult(src.name, dst.name, Verdict.PASS, "precondition satisfied")
