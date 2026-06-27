"""GateOverride — the audited escape hatch for a failed APT phase gate.

Transcribed from `bhgman_tool/ADRs/apt-gate-semantics-2026-05-25.md` §Override:

  - **No silent override.** Every override requires a record with cycle_id, phase,
    bypass_reason, authorized_by (= the user verdict text), expires_at.
  - Default `expires_at` = 24h from creation.
  - **Permanent** override requires `expires_at = 9999-12-31` AND the authorizing
    verdict text to contain the literal phrase "permanent override".
  - An override only lets a **FAIL** through (with disclosure). It cannot
    manufacture a PASS, and it never applies to SKIP/CONDITIONAL/PASS.

Time is always passed in explicitly (`now`) — no hidden clock — so expiry is
deterministic and testable. Persisting the override as a KG `:GateOverride` /
`:DecisionLog{band:'OVERRIDE_DELEGATED'}` node is the caller's job; this module
is the stdlib-only model + the proceed/disclosure decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..gate import GateResult, Verdict

__all__ = [
    "GateOverride",
    "PERMANENT_EXPIRY",
    "PERMANENT_PHRASE",
    "make_override",
    "override_allows",
    "disclosure",
]

PERMANENT_EXPIRY = "9999-12-31"
PERMANENT_PHRASE = "permanent override"
_DEFAULT_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class GateOverride:
    cycle_id: str
    phase: str
    bypass_reason: str
    authorized_by: str  # the user verdict text
    created_at: datetime
    expires_at: datetime
    permanent: bool = False
    decision_band: str = "OVERRIDE_DELEGATED"

    def active(self, now: datetime) -> bool:
        """True while the override has not expired (creation <= now < expiry)."""
        return self.created_at <= now < self.expires_at


def make_override(
    *,
    cycle_id: str,
    phase: str,
    bypass_reason: str,
    authorized_by: str,
    created_at: datetime,
    ttl: timedelta = _DEFAULT_TTL,
    permanent: bool = False,
) -> GateOverride:
    """Construct a GateOverride, enforcing the ADR's no-silent-override rules.

    Raises ValueError on a silent override (missing reason / authorization) or a
    permanent override whose authorization lacks the literal phrase.
    """
    if not bypass_reason.strip():
        raise ValueError("no silent override: bypass_reason is required")
    if not authorized_by.strip():
        raise ValueError("no silent override: authorized_by (user verdict) is required")

    if permanent:
        if PERMANENT_PHRASE not in authorized_by.lower():
            raise ValueError(
                f"permanent override requires the phrase {PERMANENT_PHRASE!r} "
                "in the authorizing verdict"
            )
        expires_at = datetime(9999, 12, 31)
    else:
        expires_at = created_at + ttl

    return GateOverride(
        cycle_id=cycle_id,
        phase=phase,
        bypass_reason=bypass_reason,
        authorized_by=authorized_by,
        created_at=created_at,
        expires_at=expires_at,
        permanent=permanent,
    )


def override_allows(result: GateResult, override: GateOverride, now: datetime) -> bool:
    """Whether `override` lets a failed gate proceed.

    Only a FAIL is overridable, the override must be active, and its phase must
    match the gate's destination phase. PASS/SKIP/CONDITIONAL are never overridden
    (there is nothing to bypass, or bypassing would forge a verdict).
    """
    if result.verdict is not Verdict.FAIL:
        return False
    if override.phase != result.to_phase:
        return False
    return override.active(now)


def disclosure(result: GateResult, override: GateOverride) -> str:
    """The mandatory stderr disclosure string — overrides are never silent."""
    expiry = "PERMANENT" if override.permanent else override.expires_at.isoformat()
    return (
        f"[GATE OVERRIDE / {override.decision_band}] "
        f"{result.from_phase}->{result.to_phase} gate FAILED "
        f"({result.gate_version}) but proceeds by override "
        f"cycle={override.cycle_id} phase={override.phase} "
        f"authorized_by={override.authorized_by!r} reason={override.bypass_reason!r} "
        f"expires={expiry}"
    )
