"""Measured-precondition resolver — establish precondition TRUTH by RUNNING the
phase's mandated tests, instead of trusting a caller-supplied bool.

The base engine's `gate.evaluate_transition` takes `precondition_met: bool`: it
models WHEN/WHAT of a gate but not HOW the precondition's truth is established
(by ADR the KG-backed resolver is delegated to dgx/SYMPOSIUM — see gate.py:11-14).
This module closes that gap for the one transition whose precondition is a LOCAL,
external fact: SCW's postcondition mandates "TDAD impact_tests" (phases.py SCW),
so `SCW -> MetaReview` can be gated on the REAL pytest exit code of those tests.

Load-bearing: truth comes from the runner's exit code, never from a caller
argument — there is deliberately NO `precondition_met` parameter on
`evaluate_measured`, so a caller cannot forge a green the tests did not earn.
The runner is injected (DIP), mirroring the engine's other I/O boundaries; the
default `pytest_runner` shells out to pytest and is not unit-tested (the
deterministic mapping exit_code -> verdict is).

# KG: finding-ooptdd-apt-engine-fix-harness-20260627 (deep-think frontier #1)
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

from .gate import GateResult, evaluate_transition

__all__ = [
    "TestRunner",
    "PreconditionEvidence",
    "MEASURABLE_TRANSITIONS",
    "is_measurable",
    "measure",
    "evaluate_measured",
    "evaluate_measured_default",
    "pytest_runner",
]

#: Transitions whose precondition is a LOCAL, externally-measurable fact (the
#: from-phase mandates tests we can actually run here). Only these are eligible
#: for measured gating; every other transition stays caller-asserted by design
#: (KG-backed resolution for the rest is delegated to dgx/SYMPOSIUM per ADR).
MEASURABLE_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({("SCW", "MetaReview")})


def is_measurable(from_phase: str, to_phase: str) -> bool:
    """Whether this transition's precondition can be established by measurement here."""
    return (from_phase, to_phase) in MEASURABLE_TRANSITIONS

#: target -> process exit code (0 == the phase's mandated tests passed).
TestRunner = Callable[[str], int]


@dataclass(frozen=True)
class PreconditionEvidence:
    """The measured truth of a phase precondition: `met` iff the tests passed."""

    met: bool
    exit_code: int
    source: str


def measure(runner: TestRunner, target: str) -> PreconditionEvidence:
    """Run `target`'s tests via `runner`; read precondition truth off the exit code."""
    code = runner(target)
    return PreconditionEvidence(met=(code == 0), exit_code=code, source=f"pytest:{target}")


def evaluate_measured(
    from_phase: str,
    to_phase: str,
    *,
    runner: TestRunner,
    target: str,
    conditional: bool = False,
    skipped: bool = False,
) -> GateResult:
    """Evaluate a transition with the precondition MEASURED, not asserted.

    There is no `precondition_met` parameter on purpose: the truth is computed
    from `runner`'s exit code, so the gate verdict for this transition is earned
    by a real test run rather than claimed by the caller.
    """
    evidence = measure(runner, target)
    return evaluate_transition(
        from_phase,
        to_phase,
        precondition_met=evidence.met,
        conditional=conditional,
        skipped=skipped,
    )


def pytest_runner(target: str) -> int:
    """Default runner: run pytest on `target` in a subprocess, return its exit code.

    Real I/O — not unit-tested. The deterministic part (exit_code -> verdict) is
    covered with injected fake runners.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", target],
        capture_output=True,
    )
    return completed.returncode


def evaluate_measured_default(
    from_phase: str,
    to_phase: str,
    *,
    target: str,
    conditional: bool = False,
    skipped: bool = False,
) -> GateResult:
    """Production measured gate — hardwires the REAL `pytest_runner`.

    Unlike `evaluate_measured`, there is NO injectable `runner`: a caller cannot
    substitute a fake runner to forge the exit code. The only thing the caller
    supplies is `target` (which tests to run); the verdict is earned by a real
    pytest process. This is the entry the CLI/MCP frontends use so that the
    measured path can never be bypassed by injection.

    NOTE (remaining gap): `target` is not yet bound to the phase's *mandated*
    impact_tests (so pointing it at unrelated passing tests still passes). Binding
    `target` to the KG/manifest impact_tests is tracked as follow-up frontier work.
    """
    return evaluate_measured(
        from_phase,
        to_phase,
        runner=pytest_runner,
        target=target,
        conditional=conditional,
        skipped=skipped,
    )
