"""APT gate verdict model.

Transcribed from `bhgman_tool/ADRs/apt-gate-semantics-2026-05-25.md`
(KG: adr-apt-gate-semantics-2026-05-25).

A gate evaluates whether a phase transition is permitted. Verdict states are
PASS | FAIL | SKIP | CONDITIONAL | ERROR. Load-bearing rule (remediation of
taliban-blocker-C9-01-2026-05-13): **SKIP is never counted as PASS.**

ERROR vs FAIL (PROM16 finding C4/A2): FAIL means the gate EVALUATED the
transition and the answer is no — precondition unmet, non-adjacent,
self-application, or a mandated test that is missing / content-drifted / did not
pass (all detected DURING measurement and folded into fail-closed exit codes).
ERROR means the gate COULD NOT EVEN DETERMINE WHAT TO MEASURE — the manifest
was unreadable or syntactically invalid JSON, or the manifest source's backend
raised (KG bolt down, etc.). Collapsing that outage into FAIL mis-reports "we
couldn't ask" as "we asked and the answer is no". Neither unlocks downstream
(fail-closed either way); the distinction is for consumers/receipts, not for
`can_advance`. The pure
`evaluate_transition` below NEVER returns ERROR — it has no I/O to fail; ERROR
originates only in the measured wrappers' outer failure path (`precondition.py`).

CONDITIONAL — what this module does and does NOT guarantee (honesty note,
PROM16 finding A3): the gate-semantics ADR mandates a follow-up VR before a
CONDITIONAL transition's downstream phase unlocks. `evaluate_transition` is a
PURE, STATELESS function — it keeps no ledger across calls, so it CANNOT
enforce that a pending CONDITIONAL was ever resolved before a later transition
PASSes. What the core guarantees is exactly `can_advance(CONDITIONAL) is
False` for the evaluated transition itself; cross-call follow-up enforcement
is delegated to the stateful runtime (KG-backed resolver, SYMPOSIUM/dgx per
adr-apt-dgx-runtime-delegation-2026-05-25), like the rest of APT's
truth-establishment. Do not read a stronger guarantee into this module.

This module is the authoritative-verdict shape; it does NOT implement the
KG-backed precondition resolver (same delegation as above). Here we model the
verdict algebra and the advance decision so tool-layer callers share one
definition.
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
    # Could-not-evaluate (infrastructure failure), as opposed to evaluated-to-no.
    # Never produced by the pure `evaluate_transition`; see the module docstring.
    ERROR = "ERROR"

    @property
    def unlocks_downstream(self) -> bool:
        """Only PASS unlocks the next phase. SKIP != PASS; CONDITIONAL needs
        follow-up; ERROR (unevaluable) is fail-closed like everything non-PASS."""
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
      0. Contradictory flags (`conditional=True` AND `skipped=True`) -> ValueError.
         A transition cannot be both skipped (never evaluated) and conditionally
         passed (evaluated, partially met) — accepting both silently returned
         SKIP by branch-order accident (PROM16 finding A3); contradictory input
         is a caller bug and is rejected loudly, for EVERY transition (input
         validation precedes semantic evaluation, including self-application).
      1. Forbidden self-application (MetaReview -> MetaReview) -> FAIL.
      2. Out-of-order / non-adjacent transition -> FAIL.
      3. Explicit skip -> SKIP (never PASS).
      4. Precondition unmet -> FAIL with the destination's gate_version.
      5. Conditional pass -> CONDITIONAL (see the module docstring: the follow-up
         VR obligation is NOT enforced by this stateless function).
      6. Otherwise -> PASS.
    """
    if conditional and skipped:
        raise ValueError(
            "conditional and skipped are mutually exclusive: a skipped transition "
            "was never evaluated, a conditional one was — pass at most one"
        )
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
