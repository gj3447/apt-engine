"""Enforcement-mode mapping (ported from gate_endpoint_prototype/gate_endpoint.py).

The gate-semantics ADR's two layers: a gate runs in INFORMATIONAL (advisory) or
BLOCKER (fail-closed) mode. This maps an internal gate outcome (pass / fail /
circuit-open) to the outward verdict the prototype emits:

    PASS | FAIL | WOULD_FAIL | OPEN_REFUSED

In INFORMATIONAL mode a failure is disclosed but advisory (WOULD_FAIL); in
BLOCKER mode it blocks (FAIL), and an open circuit becomes OPEN_REFUSED. Pure
stdlib — no FastAPI/redis — so the policy is unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["EnforcementMode", "OutwardVerdict", "enforce"]


class EnforcementMode(str, Enum):
    INFORMATIONAL = "informational"
    BLOCKER = "blocker"


class OutwardVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WOULD_FAIL = "WOULD_FAIL"
    OPEN_REFUSED = "OPEN_REFUSED"


@dataclass(frozen=True)
class EnforcedResult:
    verdict: OutwardVerdict
    advisory_only: bool


def enforce(
    *,
    passed: bool,
    mode: EnforcementMode,
    circuit_open: bool = False,
) -> EnforcedResult:
    """Map (passed, mode, circuit_open) to the outward verdict + advisory flag.

    - circuit_open: BLOCKER -> OPEN_REFUSED, INFORMATIONAL -> WOULD_FAIL (advisory).
    - passed:       always PASS (not advisory).
    - failed:       BLOCKER -> FAIL, INFORMATIONAL -> WOULD_FAIL (advisory).
    """
    advisory = mode is EnforcementMode.INFORMATIONAL

    if circuit_open:
        verdict = OutwardVerdict.OPEN_REFUSED if not advisory else OutwardVerdict.WOULD_FAIL
        return EnforcedResult(verdict, advisory)

    if passed:
        return EnforcedResult(OutwardVerdict.PASS, False)

    verdict = OutwardVerdict.WOULD_FAIL if advisory else OutwardVerdict.FAIL
    return EnforcedResult(verdict, advisory)
