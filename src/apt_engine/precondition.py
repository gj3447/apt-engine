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
    "measure",
    "evaluate_measured",
    "pytest_runner",
]

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
