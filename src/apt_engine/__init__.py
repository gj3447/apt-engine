"""apt-engine — deterministic APT phase-contract engine.

Public surface (the deterministic stdlib core):
  phases       : canonical SA->SP->ST->SCW->MetaReview->Cleanup chain + contracts.
  gate         : Verdict algebra (PASS/FAIL/SKIP/CONDITIONAL/ERROR; SKIP != PASS).
  detect       : on-disk phase detection (de-drifted from the bhgman_tool skeleton).
  precondition : measured precondition (truth by pytest, not caller bool).
  phase_map / legion : v9<->v27 reconciliation + legion commander wiring.

The layer-2 ports (gate_policy / circuit_breaker / opa / gate_override / resolver /
kg_manifest) are NOT part of this surface — they live in `apt_engine.contrib` and
are unwired dgx-prototype ports. See `docs/ADR-0002`.
"""

from __future__ import annotations

from .detect import detect_phase
from .gate import GateResult, Verdict, can_advance, evaluate_transition
from .legion import COMMANDERS, ROSTER, commander, hades_realizes, verdict_commander
from .phase_map import V9_TO_V27, is_onto, is_total, to_v9, to_v27
from .precondition import (
    MEASURABLE_TRANSITIONS,
    FileManifestSource,
    ImpactReq,
    ImpactSpec,
    ManifestSource,
    PreconditionEvidence,
    TestRunner,
    evaluate_measured,
    evaluate_measured_default,
    evaluate_measured_default_with_receipt,
    evaluate_measured_mandated,
    evaluate_measured_mandated_default,
    evaluate_measured_mandated_default_with_receipt,
    evaluate_measured_mandated_from,
    evaluate_measured_mandated_from_with_receipt,
    is_measurable,
    load_impact_manifest,
    measure,
    measure_mandated,
    pytest_collector,
    pytest_id_runner,
    pytest_runner,
)
from .receipt import (
    RECEIPT_SCHEMA_VERSION,
    GateReceipt,
    build_gate_receipt,
    runner_kind,
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
    "evaluate_measured_default_with_receipt",
    "pytest_runner",
    # mandated impact-test binding (H-C)
    "ImpactReq",
    "ImpactSpec",
    "load_impact_manifest",
    "measure_mandated",
    "evaluate_measured_mandated",
    "evaluate_measured_mandated_default",
    "evaluate_measured_mandated_from",
    "ManifestSource",
    "FileManifestSource",
    "pytest_collector",
    "pytest_id_runner",
    # auditable gate receipt (replay-checkable record of a measured gate run)
    "RECEIPT_SCHEMA_VERSION",
    "GateReceipt",
    "build_gate_receipt",
    "runner_kind",
    "evaluate_measured_mandated_from_with_receipt",
    "evaluate_measured_mandated_default_with_receipt",
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
    # NOTE: the layer-2 ports (GateOverride / enforce / CircuitBreaker / OPA /
    # resolver / kg_manifest) are intentionally NOT exported here — they are unwired dgx-
    # prototype ports under `apt_engine.contrib`. See docs/ADR-0002.
]
