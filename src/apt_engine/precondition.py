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
# KG: TASK_apt_engine_measured_gate_preflight_order_2026_07_13
# KG: CONTRACT_apt_engine_measured_gate_preflight_order_2026_07_13
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from .gate import GateResult, Verdict, evaluate_transition
from .receipt import GateReceipt, build_gate_receipt

__all__ = [
    "TestRunner",
    "PreconditionEvidence",
    "MEASURABLE_TRANSITIONS",
    "is_measurable",
    "measure",
    "evaluate_measured",
    "evaluate_measured_default",
    "evaluate_measured_default_with_receipt",
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
    # pluggable manifest trust root (the seam a KG/CI source plugs into; ADR-0003)
    "ManifestSource",
    "FileManifestSource",
    "evaluate_measured_mandated_from",
    # auditable receipt variants (same gate, + a replay-checkable GateReceipt)
    "evaluate_measured_mandated_from_with_receipt",
    "evaluate_measured_mandated_default_with_receipt",
]

#: Transitions whose precondition is a LOCAL, externally-measurable fact (the
#: from-phase mandates tests we can actually run here). Only these are eligible
#: for measured gating; every other transition stays caller-asserted by design
#: (KG-backed resolution for the rest is delegated to dgx/SYMPOSIUM per ADR).
MEASURABLE_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({("SCW", "MetaReview")})


def is_measurable(from_phase: str, to_phase: str) -> bool:
    """Whether this transition's precondition can be established by measurement here."""
    return (from_phase, to_phase) in MEASURABLE_TRANSITIONS


def _preflight_measured_transition(
    from_phase: str,
    to_phase: str,
    *,
    conditional: bool,
    skipped: bool,
) -> GateResult | None:
    """Validate caller input and settle structural results before measurement I/O.

    An optimistic precondition isolates the gate algebra that cannot depend on
    measurement truth. Structural FAIL/SKIP is terminal; PASS/CONDITIONAL means
    the wrapper must still establish the real precondition before its final gate.
    """
    result = evaluate_transition(
        from_phase,
        to_phase,
        precondition_met=True,
        conditional=conditional,
        skipped=skipped,
    )
    return result if result.verdict in (Verdict.FAIL, Verdict.SKIP) else None


def _preflight_production_with_receipt(
    from_phase: str,
    to_phase: str,
    *,
    target: str,
    gate_kind: str,
    manifest_source_kind: str = "",
    conditional: bool,
    skipped: bool,
) -> tuple[GateResult, GateReceipt] | None:
    """Settle structural and production-measurability results before I/O."""
    result = _preflight_measured_transition(
        from_phase, to_phase, conditional=conditional, skipped=skipped
    )
    if result is None and not is_measurable(from_phase, to_phase):
        result = GateResult(
            from_phase,
            to_phase,
            Verdict.FAIL,
            f"{from_phase}->{to_phase} is not locally measurable (see MEASURABLE_TRANSITIONS)",
        )
    if result is None:
        return None
    return result, build_gate_receipt(
        result,
        gate_kind=gate_kind,
        target=target,
        manifest_source_kind=manifest_source_kind,
    )


#: target -> process exit code (0 == the phase's mandated tests passed).
TestRunner = Callable[[str], int]


@dataclass(frozen=True)
class PreconditionEvidence:
    """The measured truth of a phase precondition: `met` iff the tests passed.

    `matched_node_ids` / `observed_shas` are the audit trail the receipt needs
    (which absolute node ids actually ran, which file shas were seen on disk).
    They default to empty so every existing construction site (`measure`, the
    early fail-closed returns) keeps working unchanged; only `measure_mandated`
    populates them.
    """

    met: bool
    exit_code: int
    source: str
    #: absolute node ids that matched the manifest + (for the green path) ran
    matched_node_ids: tuple[str, ...] = ()
    #: (file_path, sha256_hex) actually observed while verifying sha-pinned reqs
    observed_shas: tuple[tuple[str, str], ...] = ()


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
    preflight = _preflight_measured_transition(
        from_phase, to_phase, conditional=conditional, skipped=skipped
    )
    if preflight is not None:
        return preflight
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

    The argv isolation boundary and a PYTHONPATH shadow attack have regression
    coverage; exit-code-to-verdict mapping is covered with injected fake runners.
    """
    completed = subprocess.run(
        [sys.executable, *_PY_ISOLATION, "-m", "pytest", "-q", *_PYTEST_ISOLATION, "--", target],
        capture_output=True,
        env=_isolated_env(),
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
    preflight = _preflight_measured_transition(
        from_phase, to_phase, conditional=conditional, skipped=skipped
    )
    if preflight is not None:
        return preflight
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


def evaluate_measured_default_with_receipt(
    from_phase: str,
    to_phase: str,
    *,
    target: str,
    conditional: bool = False,
    skipped: bool = False,
) -> tuple[GateResult, GateReceipt]:
    """`evaluate_measured_default` (bare measured path) + an auditable receipt.

    WEAK path (runs whatever is under `target`; no manifest binding) — prefer the
    mandated variant for a full audit trail. But the receipt still records the
    REAL pytest exit code + evidence source (a single measured run), so a bare
    PASS/FAIL is not measurement-blank (review B fix). No mandated/observed-sha
    data exists on this path (there is no manifest), so those receipt fields stay
    empty by construction.
    """
    preflight = _preflight_production_with_receipt(
        from_phase,
        to_phase,
        target=target,
        gate_kind="measured-bare",
        conditional=conditional,
        skipped=skipped,
    )
    if preflight is not None:
        return preflight
    evidence = measure(pytest_runner, target)  # real pytest, run exactly once
    result = evaluate_transition(
        from_phase,
        to_phase,
        precondition_met=evidence.met,
        conditional=conditional,
        skipped=skipped,
    )
    return result, build_gate_receipt(
        result, gate_kind="measured-bare", target=target, evidence=evidence
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

NodeCollector = Callable[..., list[str]]  #: target[, rel_files] -> collected pytest node ids
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
    try:
        collected = collector(target, rel_files)
    except TypeError:
        collected = collector(target)
    matched: list[str] = []
    # (declared node_id, observed sha) seen while verifying pins -> receipt. Keyed
    # by the manifest node_id (NOT the absolute file path) so the receipt is
    # checkout-portable AND joins key-for-key with sha256_pinned (review A/C fix).
    observed: list[tuple[str, str]] = []
    for req in required:
        hits = [c for c in collected if _node_id_matches(c, req.node_id)]
        if len(hits) > 1:
            # A basename-only id matched >1 file -> fail closed rather than guess
            # (path-qualify the manifest entry to disambiguate). red-team-5 B2.
            return PreconditionEvidence(
                met=False,
                exit_code=7,
                source=f"impact:{target}:ambiguous:{req.node_id}",
                matched_node_ids=tuple(matched),
                observed_shas=tuple(observed),
            )
        if not hits:
            return PreconditionEvidence(
                met=False,
                exit_code=5,
                source=f"impact:{target}:missing:{req.node_id}",
                matched_node_ids=tuple(matched),
                observed_shas=tuple(observed),
            )
        abs_id = hits[0]
        if req.sha256 is not None:
            file_part = _file_of_node_id(abs_id)
            try:
                actual = hasher(file_part)
            except OSError:
                return PreconditionEvidence(
                    met=False,
                    exit_code=6,
                    source=f"impact:{target}:unhashable:{req.node_id}",
                    matched_node_ids=tuple(matched),
                    observed_shas=tuple(observed),
                )
            observed.append((req.node_id, actual))  # keyed by declared node_id
            if actual != req.sha256:
                return PreconditionEvidence(
                    met=False,
                    exit_code=6,
                    source=f"impact:{target}:sha-mismatch:{req.node_id}",
                    matched_node_ids=tuple(matched),
                    observed_shas=tuple(observed),
                )
        matched.append(abs_id)
    code = runner(matched)
    return PreconditionEvidence(
        met=(code == 0),
        exit_code=code,
        source=f"impact:{target}:{len(matched)}-mandated",
        matched_node_ids=tuple(matched),
        observed_shas=tuple(observed),
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
    preflight = _preflight_measured_transition(
        from_phase, to_phase, conditional=conditional, skipped=skipped
    )
    if preflight is not None:
        return preflight
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
# so its config is hostile-or-accidental input (red-team-4/5):
#   -o addopts=          : neutralise a target ini `addopts=--collect-only` that
#                          would let a RED test "pass" by never running.
#   --import-mode=importlib : same-basename files in sibling dirs both collect
#                          (no prepend import-mismatch that silently drops one).
#   -p no:warnings       : warning summary lines can't become phantom node ids.
#   -p no:cacheprovider  : no .pytest_cache writes under the target.
# The subprocess env is also scrubbed (`_isolated_env`): `-o addopts=` does NOT
# override the PYTEST_ADDOPTS / PYTEST_PLUGINS ENV vars, so they are stripped.
#
# This is defence in depth, NOT a security boundary. Channels it does NOT close
# (the gated party controls them): a target `conftest.py` runs ARBITRARY hook code
# — e.g. a `pytest_runtest_makereport` wrapper can rewrite a RED outcome to passed
# — and sibling helper modules and the test bodies all execute in this process.
# sha pins the named test FILE's bytes only, not its conftest. So a PASS does NOT
# imply a genuine pass unless the EXECUTION ENVIRONMENT is ALSO trusted (a CI runner
# the gated party does not control). See the TRUST BOUNDARY note above; the sound
# guarantee needs trusted CI + a non-caller (KG) manifest.
_PYTEST_ISOLATION = (
    # -I isolates the PYTHON interpreter (PROM16 P2 B3): ignores PYTHON* env vars
    # (PYTHONPATH, PYTHONSTARTUP), the user site-packages dir, and the CWD on
    # sys.path[0]. Complements the pytest-arg scrub below — a hostile/ambient
    # PYTHONPATH or a shadowing user-site module can no longer inject into the
    # measurement subprocess. It is passed to `python`, before `-m pytest`, so it
    # is prepended in the argv builders (not part of this pytest-args tuple).
    #
    # OPERATIONAL CONTRACT (verified 2026-07-13 dogfood): -I still finds the venv
    # site-packages (selected by sys.executable, not PYTHON* env), so the gate's
    # own deps AND an *installed* gated package both resolve. It does NOT honour
    # PYTHONPATH — so the gated project's mandated tests must import their package
    # from an INSTALLED distribution (editable is fine), not an ambient
    # `PYTHONPATH=src`. That is the correct posture for a CI gate (measure an
    # installed artifact, not a source tree on the path) and is exactly the
    # injection vector -I closes; a repo that only runs tests via PYTHONPATH must
    # `pip install -e .` in the runner venv first.
    "-o",
    "addopts=",
    "--import-mode=importlib",
    "-p",
    "no:warnings",
    "-p",
    "no:cacheprovider",
)

#: Interpreter-isolation flag prepended to `python` (before `-m pytest`) in every
#: measurement subprocess — see the note in `_PYTEST_ISOLATION`.
_PY_ISOLATION = ("-I",)


def _isolated_env() -> dict[str, str]:
    """Subprocess env with pytest's argv-injecting vars stripped (red-team-5 A1).

    `-o addopts=` overrides the ini addopts but NOT the PYTEST_ADDOPTS / PYTEST_PLUGINS
    ENV vars (pytest merges those by a different path), so a hostile/ambient value
    would otherwise reach the child and (e.g.) re-inject --collect-only.
    """
    return {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS")}


def pytest_collector(target: str, rel_files: list[str] | None = None) -> list[str]:
    """Production collector: collect ONLY `rel_files` under `target` -> ABS node ids.

    Collecting just the manifest-declared files (not the whole tree) means an
    unrelated broken/WIP file elsewhere cannot poison the gate (red-team-5 B1).
    pytest's rootdir is the nearest ancestor with a config (NOT necessarily
    `target`), so we force `--rootdir=base`, `cwd=base`. The target's own config and
    env are isolated. A collection PROBLEM (returncode not in {0, 5}) fails closed;
    each id is kept only if its file part is a real `.py` on disk (drops phantoms).
    """
    base = Path(target).resolve()
    args = [str(f) for f in rel_files] if rel_files else ["."]
    completed = subprocess.run(
        [
            sys.executable,
            *_PY_ISOLATION,
            "-m",
            "pytest",
            "--co",
            "-q",
            *_PYTEST_ISOLATION,
            "--rootdir",
            str(base),
            "--",  # everything after is a PATH — stops manifest node ids that
            *args,  # start with '-' from injecting pytest args
        ],
        cwd=str(base),
        capture_output=True,
        text=True,
        env=_isolated_env(),
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
        [
            sys.executable,
            *_PY_ISOLATION,
            "-m",
            "pytest",
            "-q",
            "--no-header",
            *_PYTEST_ISOLATION,
            "--",
            *node_ids,
        ],
        capture_output=True,
        text=True,
        env=_isolated_env(),
    )
    m = re.search(r"(\d+) passed", completed.stdout)
    passed = int(m.group(1)) if m else 0
    if completed.returncode == 0 and passed >= len(node_ids):
        return 0
    return completed.returncode or 1


@runtime_checkable
class ManifestSource(Protocol):
    """A trust root for each transition's mandated impact tests.

    `FileManifestSource` reads a caller-supplied file; a KG/CI-backed source
    resolves the node ids + shas from a NON-caller trust root — the real close of
    H-C (see `apt_engine.contrib.kg_manifest` and `docs/ADR-0003`).
    """

    def specs(self) -> dict[str, ImpactSpec]:
        """Return `{transition_key: ImpactSpec}` for the mandated impact tests."""
        ...


@dataclass(frozen=True)
class FileManifestSource:
    """Default `ManifestSource` — the caller-supplied `--impact-manifest` file.

    Only as trusted as that path (see the TRUST BOUNDARY note above). CI can use a
    committed file under host-enforced owner review (ADR-0003); a reachable runtime
    can swap a governed KG source at this seam (ADR-0004).
    """

    path: str

    def specs(self) -> dict[str, ImpactSpec]:
        return load_impact_manifest(self.path)


def evaluate_measured_mandated_from(
    from_phase: str,
    to_phase: str,
    *,
    target: str,
    source: ManifestSource,
    conditional: bool = False,
    skipped: bool = False,
) -> GateResult:
    """Production mandated gate resolving the manifest from a `ManifestSource`.

    The source IS the trust root: `FileManifestSource` (caller file) or a KG/CI
    source (non-caller). No injectable collector/runner — the tests' pass/fail is
    established by real pytest. Recoverable source or measurement-plumbing
    exceptions fail closed as ERROR; missing, drifted, or unhashable mandated tests
    are evaluated evidence and fail closed as FAIL.

    Thin wrapper over `evaluate_measured_mandated_from_with_receipt` that drops
    the receipt — identical verdict behaviour, kept for callers that don't audit.
    """
    result, _receipt = evaluate_measured_mandated_from_with_receipt(
        from_phase,
        to_phase,
        target=target,
        source=source,
        conditional=conditional,
        skipped=skipped,
    )
    return result


def evaluate_measured_mandated_from_with_receipt(
    from_phase: str,
    to_phase: str,
    *,
    target: str,
    source: ManifestSource,
    conditional: bool = False,
    skipped: bool = False,
) -> tuple[GateResult, GateReceipt]:
    """Same gate as `evaluate_measured_mandated_from`, plus an auditable receipt.

    The receipt records the transition, verdict, mandated + matched node ids, the
    manifest-pinned vs. on-disk-observed shas, the pytest exit code, the manifest
    trust-root kind, and the runner tier (ci/local) — turning a green into a
    replay-checkable record. The receipt is emitted on every path that returns a
    GateResult (including not-measurable and unevaluable fail-closed paths). Caller
    bugs raise before evaluation and therefore return neither a result nor a receipt.
    """
    source_kind = type(source).__name__
    preflight = _preflight_production_with_receipt(
        from_phase,
        to_phase,
        target=target,
        gate_kind="measured-mandated",
        manifest_source_kind=source_kind,
        conditional=conditional,
        skipped=skipped,
    )
    if preflight is not None:
        return preflight
    try:
        manifest = source.specs()
        spec = manifest.get(_txn_key(from_phase, to_phase))
        required = spec.required if spec else ()
        evidence = measure_mandated(
            target, required, collector=pytest_collector, runner=pytest_id_runner
        )
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        # Could-not-evaluate -> ERROR, NOT FAIL (PROM16 C4): an unreadable manifest,
        # syntactically invalid JSON, or a recoverable source/measurement exception
        # (a KG source raises ValueError when bolt is down) means the gate never
        # determined WHAT to measure — reporting
        # that as FAIL would read as "we asked and the answer is no". ERROR is still
        # fail-closed (can_advance is False), so process/CLI exit behaviour is
        # unchanged; only the verdict label distinguishes an outage from an earned
        # red. (Per-test problems found DURING measurement — missing / sha-drifted /
        # unhashable mandated test — are handled inside measure_mandated as FAIL exit
        # codes, not here.) red-team LOW-7. Only the MEASUREMENT is absorbed:
        # evaluate_transition runs below, OUTSIDE this try, so a caller bug
        # (contradictory flags -> ValueError, unknown phase -> KeyError) still raises
        # loudly, consistent with every other gate entry point.
        result = GateResult(
            from_phase,
            to_phase,
            Verdict.ERROR,
            f"impact gate unevaluable: {exc}",
        )
        return result, build_gate_receipt(
            result,
            gate_kind="measured-mandated",
            target=target,
            manifest_source_kind=source_kind,
            error=str(exc),
        )
    result = evaluate_transition(
        from_phase,
        to_phase,
        precondition_met=evidence.met,
        conditional=conditional,
        skipped=skipped,
    )
    receipt = build_gate_receipt(
        result,
        gate_kind="measured-mandated",
        target=target,
        manifest_source_kind=source_kind,
        evidence=evidence,
        required=required,
    )
    return result, receipt


def evaluate_measured_mandated_default(
    from_phase: str,
    to_phase: str,
    *,
    target: str,
    manifest_path: str,
    conditional: bool = False,
    skipped: bool = False,
) -> GateResult:
    """Production mandated gate over a caller-supplied manifest FILE.

    Thin wrapper over `evaluate_measured_mandated_from` with a `FileManifestSource`.
    Pointing `target` at an unrelated passing dir FAILs (its tests do not match the
    manifest's mandated node ids).
    """
    return evaluate_measured_mandated_from(
        from_phase,
        to_phase,
        target=target,
        source=FileManifestSource(manifest_path),
        conditional=conditional,
        skipped=skipped,
    )


def evaluate_measured_mandated_default_with_receipt(
    from_phase: str,
    to_phase: str,
    *,
    target: str,
    manifest_path: str,
    conditional: bool = False,
    skipped: bool = False,
) -> tuple[GateResult, GateReceipt]:
    """`evaluate_measured_mandated_default` + an auditable `GateReceipt`.

    Thin wrapper over `evaluate_measured_mandated_from_with_receipt` with a
    `FileManifestSource` — the entry the CLI `--receipt-out` and the MCP
    `apt_gate_measured` frontends use.
    """
    return evaluate_measured_mandated_from_with_receipt(
        from_phase,
        to_phase,
        target=target,
        source=FileManifestSource(manifest_path),
        conditional=conditional,
        skipped=skipped,
    )
