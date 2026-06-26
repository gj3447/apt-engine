"""apt-engine — deterministic APT phase-contract engine.

Public surface:
  phases : canonical SA->SP->ST->SCW->MetaReview->Cleanup chain + contracts.
  gate   : Verdict algebra (PASS/FAIL/SKIP/CONDITIONAL; SKIP != PASS).
  detect : on-disk phase detection (de-drifted from the bhgman_tool skeleton).
"""

from __future__ import annotations

from .detect import detect_phase
from .circuit_breaker import CircuitBreaker, InMemoryStore, State
from .gate import GateResult, Verdict, can_advance, evaluate_transition
from .gate_override import GateOverride, disclosure, make_override, override_allows
from .gate_policy import EnforcementMode, OutwardVerdict, enforce
from .legion import COMMANDERS, ROSTER, commander, hades_realizes, verdict_commander
from .phase_map import V9_TO_V27, is_onto, is_total, to_v9, to_v27
from .phases import CHAIN, PHASES, Phase, is_self_application, next_phase, phase_by_name

__version__ = "0.1.0"

__all__ = [
    "CHAIN",
    "PHASES",
    "Phase",
    "phase_by_name",
    "next_phase",
    "is_self_application",
    "Verdict",
    "GateResult",
    "can_advance",
    "evaluate_transition",
    "detect_phase",
    # (a) v9<->v27 reconciliation
    "V9_TO_V27",
    "to_v27",
    "to_v9",
    "is_total",
    "is_onto",
    # (b) legion wiring
    "COMMANDERS",
    "ROSTER",
    "commander",
    "verdict_commander",
    "hades_realizes",
    # gate override (audited escape hatch)
    "GateOverride",
    "make_override",
    "override_allows",
    "disclosure",
    # gate enforcement + resilience (ported from gate_endpoint_prototype)
    "EnforcementMode",
    "OutwardVerdict",
    "enforce",
    "CircuitBreaker",
    "InMemoryStore",
    "State",
]
