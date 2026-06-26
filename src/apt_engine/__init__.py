"""apt-engine — deterministic APT phase-contract engine.

Public surface:
  phases : canonical SA->SP->ST->SCW->MetaReview->Cleanup chain + contracts.
  gate   : Verdict algebra (PASS/FAIL/SKIP/CONDITIONAL; SKIP != PASS).
  detect : on-disk phase detection (de-drifted from the bhgman_tool skeleton).
"""

from __future__ import annotations

from .detect import detect_phase
from .gate import GateResult, Verdict, can_advance, evaluate_transition
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
]
