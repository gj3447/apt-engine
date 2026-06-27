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

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .gate import GateResult, Verdict, evaluate_transition

__all__ = [
    "TestRunner",
    "PreconditionEvidence",
    "MEASURABLE_TRANSITIONS",
    "is_measurable",
    "measure",
    "evaluate_measured",
    "evaluate_measured_default",
    "pytest_runner",
    # mandated impact-test binding (H-C: target bound to the phase's tests)
    "ImpactSpec",
    "NodeCollector",
    "IdRunner",
    "load_impact_manifest",
    "measure_mandated",
    "evaluate_measured_mandated",
    "pytest_collector",
    "pytest_id_runner",
    "evaluate_measured_mandated_default",
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

    NOTE: this WEAK variant runs whatever is under `target`, so an unrelated
    passing dir satisfies it. For the mandated binding (target bound to the
    phase's declared impact_tests), use `evaluate_measured_mandated_default`.
    """
    if not is_measurable(from_phase, to_phase):
        return GateResult(
            from_phase, to_phase, Verdict.FAIL,
            f"{from_phase}->{to_phase} is not locally measurable (see MEASURABLE_TRANSITIONS)",
        )
    return evaluate_measured(
        from_phase,
        to_phase,
        runner=pytest_runner,
        target=target,
        conditional=conditional,
        skipped=skipped,
    )


# --------------------------------------------------------------------------- #
#  Mandated impact-test binding (H-C)                                          #
#  The bare measured gate above runs WHATEVER is under `target`, so an         #
#  unrelated passing dir satisfies it. Below, the precondition is met only     #
#  when the tests the transition MANDATES (declared in a manifest, matched by  #
#  node-id substring) are actually collected under the target AND pass. This   #
#  binds by NAME, not content (a name-matching trivial test still satisfies    #
#  it); exact node-id binding is follow-up. The manifest is caller-supplied    #
#  (`--impact-manifest`), so it is only as trusted as that path — empty/        #
#  whitespace substrings are rejected (they would match everything).           #
# --------------------------------------------------------------------------- #

NodeCollector = Callable[[str], list[str]]  #: target -> collected pytest node ids
IdRunner = Callable[[list[str]], int]  #: node ids -> exit code


@dataclass(frozen=True)
class ImpactSpec:
    """The mandated impact-tests a transition's precondition requires.

    `required` is a tuple of non-empty node-id SUBSTRINGS: a run satisfies the
    precondition only if the collected tests whose node id contains one of them
    actually run AND pass. This binds by NAME, not content — a trivially-passing
    test named to match still satisfies it; binding to an exact node-id set is
    follow-up work. Empty/whitespace substrings are rejected at load time (they
    would match every node id, defeating the bind).
    """

    transition: tuple[str, str]
    required: tuple[str, ...]


def _txn_key(from_phase: str, to_phase: str) -> str:
    return f"{from_phase}->{to_phase}"


def load_impact_manifest(path: str) -> dict[str, ImpactSpec]:
    """Load `{"SCW->MetaReview": {"required": ["impact"]}}` -> {key: ImpactSpec}."""
    data = json.loads(Path(path).read_text())
    out: dict[str, ImpactSpec] = {}
    for key, spec in data.items():
        frm, _, to = key.partition("->")
        # Reject empty/whitespace substrings: "" matches every node id and would
        # let any passing dir forge the precondition (red-team HIGH-1).
        required = tuple(r for r in spec.get("required", ()) if isinstance(r, str) and r.strip())
        out[key] = ImpactSpec(transition=(frm, to), required=required)
    return out


def measure_mandated(
    target: str,
    required: tuple[str, ...],
    *,
    collector: NodeCollector,
    runner: IdRunner,
) -> PreconditionEvidence:
    """Met iff the MANDATED tests are present under `target` AND pass.

    exit_code carries the signal: 4 = nothing mandated declared, 5 = no mandated
    test collected (the forge case), else the runner's real exit code on exactly
    the mandated node ids.
    """
    # Defence in depth: drop empty/whitespace substrings (they match everything).
    required = tuple(r for r in required if isinstance(r, str) and r.strip())
    if not required:
        return PreconditionEvidence(met=False, exit_code=4, source="impact:no-mandated-declared")
    collected = collector(target)
    matched = [nid for nid in collected if any(r in nid for r in required)]
    if not matched:
        return PreconditionEvidence(
            met=False, exit_code=5, source=f"impact:{target}:0-mandated-collected"
        )
    code = runner(matched)
    return PreconditionEvidence(
        met=(code == 0), exit_code=code, source=f"impact:{target}:{len(matched)}-mandated"
    )


def evaluate_measured_mandated(
    from_phase: str,
    to_phase: str,
    *,
    target: str,
    manifest: dict[str, ImpactSpec],
    collector: NodeCollector,
    runner: IdRunner,
    conditional: bool = False,
    skipped: bool = False,
) -> GateResult:
    """Evaluate a transition whose precondition is its MANDATED impact_tests.

    The mandated tests are resolved from `manifest` by transition (not caller
    args). If the transition is absent from the manifest it is not measurable
    here and the gate FAILs closed.
    """
    spec = manifest.get(_txn_key(from_phase, to_phase))
    required = spec.required if spec else ()
    evidence = measure_mandated(target, required, collector=collector, runner=runner)
    return evaluate_transition(
        from_phase, to_phase, precondition_met=evidence.met,
        conditional=conditional, skipped=skipped,
    )


def pytest_collector(target: str) -> list[str]:
    """Production collector: `pytest --co -q target` -> ABSOLUTE node ids.

    pytest prints ids relative to rootdir(=target); we absolutise them so the
    runner can execute exactly those ids from any working directory.
    """
    base = Path(target).resolve()
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--co", "-q", str(base)],
        capture_output=True, text=True,
    )
    ids: list[str] = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if "::" not in line:
            continue
        file_part = line.split("::", 1)[0]
        ids.append(line if Path(file_part).is_absolute() else str(base / line))
    return ids


def pytest_id_runner(node_ids: list[str]) -> int:
    """Production runner: run exactly the mandated node ids; return the exit code.

    Never runs with an empty id list (that would mean "run everything") — an
    empty mandated set is handled upstream in `measure_mandated` as UNMET.
    """
    if not node_ids:
        return 5  # pytest's "no tests collected" code -> treated as unmet
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *node_ids],
        capture_output=True,
    )
    return completed.returncode


def evaluate_measured_mandated_default(
    from_phase: str,
    to_phase: str,
    *,
    target: str,
    manifest_path: str,
    conditional: bool = False,
    skipped: bool = False,
) -> GateResult:
    """Production mandated gate — hardwires the real pytest collector + runner.

    No injectable collector/runner: the caller supplies only `target` and the
    manifest path; the mandated tests and their pass/fail are established by real
    pytest. Pointing `target` at an unrelated passing dir FAILs (its tests do not
    match the manifest's mandated node ids).
    """
    if not is_measurable(from_phase, to_phase):
        return GateResult(
            from_phase, to_phase, Verdict.FAIL,
            f"{from_phase}->{to_phase} is not locally measurable (see MEASURABLE_TRANSITIONS)",
        )
    try:
        manifest = load_impact_manifest(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        # Fail closed instead of leaking a traceback (red-team LOW-7).
        return GateResult(
            from_phase, to_phase, Verdict.FAIL, f"impact manifest unreadable: {exc}",
        )
    return evaluate_measured_mandated(
        from_phase, to_phase, target=target, manifest=manifest,
        collector=pytest_collector, runner=pytest_id_runner,
        conditional=conditional, skipped=skipped,
    )
