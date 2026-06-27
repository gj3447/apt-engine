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

import hashlib
import json
import re
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
    "ImpactReq",
    "ImpactSpec",
    "NodeCollector",
    "IdRunner",
    "FileHasher",
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
            from_phase,
            to_phase,
            Verdict.FAIL,
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
#  when the tests the transition MANDATES (declared in a manifest as EXACT      #
#  node ids, optionally content-pinned by sha256) are collected under the       #
#  target AND pass. With sha256 the bind rejects a same-named but               #
#  different-content test (content DRIFT); without it, name-only.               #
#                                                                               #
#  TRUST BOUNDARY (do not over-read): the manifest — node ids AND shas — is      #
#  caller-supplied (`--impact-manifest`). A forger who controls the manifest     #
#  just pins the sha of their OWN forged test and passes, so sha does NOT close  #
#  the forge against an adversary who writes the manifest. It only defends a     #
#  TRUSTED manifest (node ids + shas authored by a non-caller trust root, e.g.   #
#  KG/CI/signed) against on-disk test-content drift. Anchoring the manifest in   #
#  that trust root is out of scope here (delegated, like the rest of APT's       #
#  truth-establishment, per adr-apt-dgx-runtime-delegation).                     #
# --------------------------------------------------------------------------- #

NodeCollector = Callable[[str, list[str]], list[str]]  #: (target, rel_files) -> node ids
IdRunner = Callable[[list[str]], int]  #: node ids -> exit code
FileHasher = Callable[[str], str]  #: file path -> sha256 hex


@dataclass(frozen=True)
class ImpactReq:
    """One mandated impact test: an exact `file.py::testname` node id plus an
    optional sha256 of the test FILE.

    With `sha256` set, a same-named but different-content test is REJECTED —
    BUT only relative to a TRUSTED manifest: since the manifest (incl. the sha)
    is caller-supplied, a forger who writes it can pin their own forged test's
    sha and pass. sha closes test-content DRIFT, not a manifest-controlling
    adversary. Without sha, the bind is name-only. See the TRUST BOUNDARY note above.
    """

    node_id: str
    sha256: str | None = None


@dataclass(frozen=True)
class ImpactSpec:
    """The mandated impact-tests a transition's precondition requires.

    `required` is a tuple of `ImpactReq` (exact node ids, optionally sha-pinned).
    The precondition is met only if EVERY required test is collected under the
    target, its sha256 matches (when pinned), and the set runs green.
    """

    transition: tuple[str, str]
    required: tuple["ImpactReq", ...]


def _txn_key(from_phase: str, to_phase: str) -> str:
    return f"{from_phase}->{to_phase}"


def _norm_node_id(node_id: str) -> str:
    """Reduce a pytest node id to a manifest-comparable suffix."""
    file_part, sep, rest = node_id.partition("::")
    base = Path(file_part).name
    return f"{base}::{rest}" if sep else base


def _node_id_matches(collected: str, required: str) -> bool:
    """Whether a collected (possibly absolute) node id satisfies a required one.

    Matches by PATH SUFFIX at a path boundary, so a path-qualified required id
    `tests/unit/test_x.py::t` matches `/base/tests/unit/test_x.py::t` but NOT
    `/base/tests/integration/test_x.py::t` (red-team-5 B2 — directories are not
    collapsed to basenames). A basename-only required id `test_x.py::t` matches
    BOTH siblings, which `measure_mandated` then treats as ambiguous (fail-closed).
    """
    return collected == required or collected.endswith("/" + required)


def _file_of_node_id(node_id: str) -> str:
    """The file-path portion of a pytest node id (before `::`)."""
    return node_id.partition("::")[0]


def _sha256_file(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _parse_req(entry: object) -> "ImpactReq | None":
    """Parse a manifest `required` entry: a string node id, or {node_id, sha256}."""
    if isinstance(entry, str):
        node_id, sha = entry, None
    elif isinstance(entry, dict):
        node_id, sha = entry.get("node_id", ""), entry.get("sha256")
    else:
        return None
    # An exact node id must contain '::' — a bare substring (e.g. "impact") is
    # rejected so it can never silently match by name (red-team HIGH-1/HIGH-2).
    if isinstance(node_id, str) and node_id.strip() and "::" in node_id:
        # Keep the node id AS DECLARED (path-qualified) — do NOT collapse to
        # basename, so `tests/unit/test_x.py::t` stays distinct from a sibling.
        return ImpactReq(
            node_id=node_id.strip(),
            sha256=sha if isinstance(sha, str) and sha.strip() else None,
        )
    return None


def load_impact_manifest(path: str) -> dict[str, ImpactSpec]:
    """Load a manifest -> {transition_key: ImpactSpec}.

    Format: `{"SCW->MetaReview": {"required": [
        {"node_id": "test_scw.py::test_contract", "sha256": "<hex>"},
        "test_other.py::test_x"   # string shorthand (name-only, no sha)
    ]}}`
    """
    data = json.loads(Path(path).read_text())
    out: dict[str, ImpactSpec] = {}
    if not isinstance(data, dict):
        return out  # malformed (e.g. a JSON array) -> no mandated transitions
    for key, spec in data.items():
        if not isinstance(spec, dict):
            continue  # skip malformed transition entries instead of crashing
        frm, _, to = key.partition("->")
        reqs = tuple(r for r in (_parse_req(e) for e in spec.get("required", ())) if r)
        out[key] = ImpactSpec(transition=(frm, to), required=reqs)
    return out


def measure_mandated(
    target: str,
    required: "tuple[ImpactReq, ...]",
    *,
    collector: NodeCollector,
    runner: IdRunner,
    hasher: FileHasher = _sha256_file,
) -> PreconditionEvidence:
    """Met iff EVERY mandated test is collected under `target`, content-matches
    (when sha-pinned), and the set runs green.

    exit_code signal: 4 = nothing mandated declared, 5 = a required node id is
    missing (structural forge), 6 = a sha256 mismatch (content forge), else the
    runner's real exit code on exactly the mandated node ids.
    """
    required = tuple(r for r in required if r.node_id and "::" in r.node_id)
    if not required:
        return PreconditionEvidence(met=False, exit_code=4, source="impact:no-mandated-declared")
    # Scope collection to ONLY the manifest-declared files (red-team-5 B1): an
    # unrelated broken/WIP file elsewhere in the tree must not poison the gate.
    rel_files = sorted({_file_of_node_id(r.node_id) for r in required})
    collected = collector(target, rel_files)
    matched: list[str] = []
    for req in required:
        hits = [c for c in collected if _node_id_matches(c, req.node_id)]
        if len(hits) > 1:
            # A basename-only id matched >1 file -> fail closed rather than guess
            # (path-qualify the manifest entry to disambiguate). red-team-5 B2.
            return PreconditionEvidence(
                met=False, exit_code=7, source=f"impact:{target}:ambiguous:{req.node_id}"
            )
        if not hits:
            return PreconditionEvidence(
                met=False, exit_code=5, source=f"impact:{target}:missing:{req.node_id}"
            )
        abs_id = hits[0]
        if req.sha256 is not None:
            try:
                actual = hasher(_file_of_node_id(abs_id))
            except OSError:
                return PreconditionEvidence(
                    met=False, exit_code=6, source=f"impact:{target}:unhashable:{req.node_id}"
                )
            if actual != req.sha256:
                return PreconditionEvidence(
                    met=False, exit_code=6, source=f"impact:{target}:sha-mismatch:{req.node_id}"
                )
        matched.append(abs_id)
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
    hasher: FileHasher = _sha256_file,
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
    evidence = measure_mandated(target, required, collector=collector, runner=runner, hasher=hasher)
    return evaluate_transition(
        from_phase,
        to_phase,
        precondition_met=evidence.met,
        conditional=conditional,
        skipped=skipped,
    )


# Isolate the TARGET's own pytest config — the gated party owns the working tree,
# so its config is hostile-or-accidental input (red-team-4 BLOCKER/HIGH):
#   -o addopts=          : neutralise a target `addopts=--collect-only` that would
#                          let a RED test "pass" by never running.
#   --import-mode=importlib : same-basename files in sibling dirs both collect
#                          (no prepend import-mismatch that silently drops one).
#   -p no:warnings       : warning summary lines can't become phantom node ids.
#   -p no:cacheprovider  : no .pytest_cache writes under the target.
# This is defence in depth, NOT a full security boundary — see the TRUST BOUNDARY
# note above: a party controlling the EXECUTION ENVIRONMENT can still subvert a
# working-tree gate; the sound guarantee needs a trusted runner (CI), not this.
_PYTEST_ISOLATION = (
    "-o",
    "addopts=",
    "--import-mode=importlib",
    "-p",
    "no:warnings",
    "-p",
    "no:cacheprovider",
)


def pytest_collector(target: str) -> list[str]:
    """Production collector: collect under `target` -> ABSOLUTE node ids.

    pytest's rootdir is the nearest ancestor with a config (NOT necessarily
    `target`), so we force `--rootdir=base`, `cwd=base`, arg `.`. The target's own
    config is isolated (`_PYTEST_ISOLATION`). A collection PROBLEM (returncode not
    in {0, 5}) fails closed (no ids -> 'missing'); each id is kept only if its file
    part is a real `.py` on disk (drops phantom ids from stray `::` lines).
    """
    base = Path(target).resolve()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--co",
            "-q",
            *_PYTEST_ISOLATION,
            "--rootdir",
            str(base),
            ".",
        ],
        cwd=str(base),
        capture_output=True,
        text=True,
    )
    if completed.returncode not in (0, 5):
        return []  # collection error (import mismatch, etc.) -> fail closed
    ids: list[str] = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if "::" not in line:
            continue
        file_part, _, rest = line.partition("::")
        if not file_part.endswith(".py"):
            continue  # a non-test line that happens to contain '::'
        abs_file = file_part if Path(file_part).is_absolute() else str(base / file_part)
        if not Path(abs_file).is_file():
            continue  # phantom id (e.g. from a warning message) -> drop
        ids.append(f"{abs_file}::{rest}")
    return ids


def pytest_id_runner(node_ids: list[str]) -> int:
    """Production runner: run exactly the mandated (absolute) node ids; exit code.

    Config-isolated. Returns 0 only if the tests actually RAN and passed: exit 0
    AND at least len(node_ids) reported "passed". The passed-count guard defeats a
    target `--collect-only` (which would exit 0 with 0 passed). Empty id list -> 5.
    """
    if not node_ids:
        return 5  # pytest's "no tests collected" code -> treated as unmet
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", *_PYTEST_ISOLATION, *node_ids],
        capture_output=True,
        text=True,
    )
    m = re.search(r"(\d+) passed", completed.stdout)
    passed = int(m.group(1)) if m else 0
    if completed.returncode == 0 and passed >= len(node_ids):
        return 0
    return completed.returncode or 1


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
            from_phase,
            to_phase,
            Verdict.FAIL,
            f"{from_phase}->{to_phase} is not locally measurable (see MEASURABLE_TRANSITIONS)",
        )
    try:
        manifest = load_impact_manifest(manifest_path)
        return evaluate_measured_mandated(
            from_phase,
            to_phase,
            target=target,
            manifest=manifest,
            collector=pytest_collector,
            runner=pytest_id_runner,
            conditional=conditional,
            skipped=skipped,
        )
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        # Fail closed instead of leaking a traceback — unreadable/malformed
        # manifest, or a hash/collect I/O error (red-team LOW-7).
        return GateResult(
            from_phase,
            to_phase,
            Verdict.FAIL,
            f"impact gate unevaluable: {exc}",
        )
