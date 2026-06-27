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
from .precondition import (
    MEASURABLE_TRANSITIONS,
    ImpactSpec,
    PreconditionEvidence,
    TestRunner,
    evaluate_measured,
    evaluate_measured_default,
    evaluate_measured_mandated,
    evaluate_measured_mandated_default,
    is_measurable,
    load_impact_manifest,
    measure,
    measure_mandated,
    pytest_collector,
    pytest_id_runner,
    pytest_runner,
)
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
    # measured precondition (truth by pytest exit code, not caller bool)
    "TestRunner",
    "PreconditionEvidence",
    "MEASURABLE_TRANSITIONS",
    "is_measurable",
    "measure",
    "evaluate_measured",
    "evaluate_measured_default",
    "pytest_runner",
    # mandated impact-test binding (H-C)
    "ImpactSpec",
    "load_impact_manifest",
    "measure_mandated",
    "evaluate_measured_mandated",
    "evaluate_measured_mandated_default",
    "pytest_collector",
    "pytest_id_runner",
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
