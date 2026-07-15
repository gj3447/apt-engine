"""Gate receipt — an auditable, replay-checkable record of a measured gate run.

The measured gate (`precondition.evaluate_measured_mandated_from`) currently only
answers "PASS iff the mandated tests ran green" and leaves no durable trace of
WHAT ran, WITH WHICH content, and WHEN. A green CI job is trustworthy in the
moment but disputable later. `GateReceipt` turns "trust me it passed" into "here
is the receipt": the transition, verdict, the mandated node ids, the sha256s the
manifest pinned vs. the ones actually observed on disk, the pytest exit code, the
manifest trust-root kind, and the runner identity (ci vs. local).

This is the operational-substrate move (reproducibility + audit), NOT a security
boundary and NOT a cryptographic attestation. There is no signing key here; a
receipt is a diffable JSON record whose `audit_key()` is the content-addressable,
checkout-portable fingerprint (the receipt object itself is not hashable — it has
dict fields). It is the stdlib-scale analogue of an in-toto/SLSA provenance
statement, and the prerequisite artifact for `apt-engine verify --replay`
(re-derive the verdict + re-observe on-disk shas and diff `audit_key()` against
this receipt, without re-running pytest — see `apt_engine.replay`).

Honest boundary (mirrors precondition.py's TRUST BOUNDARY note): a receipt
records what the gate observed; it does not make the observation itself
un-subvertible. `runner == "local"` means defence-in-depth only; the sound
guarantee still needs a trusted CI runner + a non-caller manifest (ADR-0003).

Stdlib only — no runtime deps (belongs to the KG-free core).

# KG: rf-prom16-apt-gatereceipt-emitter (cycle prom16-apt-engine-hardening-2026-07-13,
#     4-cell consensus B1/B4/D1/D4), lesson-prom16-apt-engine-hardening-2026-07-13
"""

from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # avoid import cycle at runtime (precondition imports receipt)
    from .gate import GateResult
    from .precondition import ImpactReq, PreconditionEvidence

__all__ = [
    "RECEIPT_SCHEMA_VERSION",
    "GateReceipt",
    "runner_kind",
    "build_gate_receipt",
]

#: Bump when the receipt field set changes in a non-backward-compatible way. A
#: replay verifier keys off this to refuse comparing incompatible receipts.
RECEIPT_SCHEMA_VERSION = "apt-engine/gate-receipt/v1"

#: Env var CI runners set (GitHub Actions, GitLab, CircleCI, ... all set CI=true).
#: `runner == "ci"` is the "trusted runner" tier ADR-0003 names; "local" is
#: defence-in-depth only. This makes that distinction machine-checkable rather
#: than prose-only.
_CI_ENV = "CI"


def runner_kind(env: dict[str, str] | None = None) -> str:
    """"ci" iff a CI env var is set (truthy, not literally 'false'/'0'), else "local".

    NOTE: this is a SELF-ASSERTED hint, not a verified fact — a local caller can
    export `CI=true`. Nothing in the engine gates on it; it only labels the
    receipt's provenance tier. The sound "trusted runner" guarantee is an
    out-of-band property of the actual CI environment (ADR-0003), not of this flag.
    """
    src = os.environ if env is None else env
    val = src.get(_CI_ENV, "").strip().lower()
    return "ci" if val not in ("", "false", "0", "no") else "local"


@dataclass(frozen=True)
class GateReceipt:
    """A durable, diffable record of one gate evaluation.

    `audit_key()` is the CHECKOUT-PORTABLE fingerprint: two runs of the same gate
    over the same declared manifest + same on-disk test content compare equal for
    replay even across different machines/checkouts and at different times. To
    make that true, `audit_key()` excludes both the run-context fields
    (`timestamp_utc`, `runner`, `python_version`, `apt_engine_version`) AND the
    checkout-specific path fields (`target`, `matched_node_ids` [absolute],
    `evidence_source` [embeds `target`]). Content drift is still caught because
    `sha256_observed` is keyed by the DECLARED node id (portable) and joins
    key-for-key with `sha256_pinned`, so a content change flips a value in the
    key. `reason`/`gate_version` are also excluded (derivable from verdict+phase).
    Those excluded fields remain on the receipt as human-readable display data.
    """

    schema_version: str
    from_phase: str
    to_phase: str
    verdict: str
    #: which gate path produced this: "measured-mandated" | "measured-bare" | "asserted"
    gate_kind: str
    reason: str
    gate_version: str | None
    target: str | None
    #: type name of the ManifestSource trust root (e.g. "FileManifestSource"), "" if none
    manifest_source_kind: str
    #: node ids the manifest DECLARED as mandated (as-declared, path-qualified)
    mandated_node_ids: tuple[str, ...]
    #: absolute node ids actually collected + run (empty if the gate never got that far)
    matched_node_ids: tuple[str, ...]
    #: node_id -> sha256 the manifest PINNED (only the pinned ones)
    sha256_pinned: dict[str, str]
    #: declared node id -> sha256 actually OBSERVED on disk during verification
    sha256_observed: dict[str, str]
    #: the measured precondition's pytest exit code (None if no measurement ran)
    pytest_exit_code: int | None
    #: the PreconditionEvidence.source audit string (e.g. "impact:<target>:2-mandated")
    evidence_source: str | None
    #: "ci" (trusted runner tier) | "local" (defence-in-depth only)
    runner: str
    timestamp_utc: str
    python_version: str
    apt_engine_version: str
    #: set when the outer gate evaluation raised a recoverable exception before a
    #: measured verdict; ordinary missing/drift/unhashable evidence stays a FAIL
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        """JSON-ready dict (tuples -> lists, dicts kept, sorted keys stable in to_json)."""
        return {
            "schema_version": self.schema_version,
            "from_phase": self.from_phase,
            "to_phase": self.to_phase,
            "verdict": self.verdict,
            "gate_kind": self.gate_kind,
            "reason": self.reason,
            "gate_version": self.gate_version,
            "target": self.target,
            "manifest_source_kind": self.manifest_source_kind,
            "mandated_node_ids": list(self.mandated_node_ids),
            "matched_node_ids": list(self.matched_node_ids),
            "sha256_pinned": dict(self.sha256_pinned),
            "sha256_observed": dict(self.sha256_observed),
            "pytest_exit_code": self.pytest_exit_code,
            "evidence_source": self.evidence_source,
            "runner": self.runner,
            "timestamp_utc": self.timestamp_utc,
            "python_version": self.python_version,
            "apt_engine_version": self.apt_engine_version,
            "error": self.error,
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    def audit_key(self) -> tuple[object, ...]:
        """The REPRODUCIBLE, checkout-portable fingerprint — what a replay must match.

        `receipt_a.audit_key() == receipt_b.audit_key()` iff the two gate runs are
        the same *decision* over the same *declared evidence*, independent of when
        or where they ran. Excluded (so replay across machines/checkouts is
        sound): `timestamp_utc`, `runner`, `python_version`, `apt_engine_version`
        (run-context) and `target`, `matched_node_ids`, `evidence_source`
        (checkout-specific absolute paths), plus `reason`/`gate_version`
        (derivable from verdict+phase). `sha256_observed` IS included but is keyed
        by the declared node id, so it stays portable while still flipping on
        content drift. This is exactly what `verify --replay` compares.
        """
        return (
            self.schema_version,
            self.from_phase,
            self.to_phase,
            self.verdict,
            self.gate_kind,
            self.manifest_source_kind,
            self.mandated_node_ids,
            tuple(sorted(self.sha256_pinned.items())),
            tuple(sorted(self.sha256_observed.items())),
            self.pytest_exit_code,
            self.error,
        )


def build_gate_receipt(
    result: "GateResult",
    *,
    gate_kind: str,
    target: str | None = None,
    manifest_source_kind: str = "",
    evidence: "PreconditionEvidence | None" = None,
    required: "tuple[ImpactReq, ...]" = (),
    error: str | None = None,
    env: dict[str, str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> GateReceipt:
    """Assemble a `GateReceipt` from a gate result (+ optional measured evidence).

    `clock`/`env` are injectable so tests get a deterministic timestamp/runner
    without monkeypatching module state. `required` (the manifest's declared
    ImpactReqs) supplies the mandated node ids + pinned shas; `evidence` (from
    `measure_mandated`) supplies the observed shas + matched node ids + exit code.
    """
    now = (clock or _utc_now)()
    mandated = tuple(r.node_id for r in required)
    pinned = {r.node_id: r.sha256 for r in required if r.sha256 is not None}
    matched: tuple[str, ...] = ()
    observed: dict[str, str] = {}
    exit_code: int | None = None
    evidence_source: str | None = None
    if evidence is not None:
        matched = tuple(evidence.matched_node_ids)
        observed = dict(evidence.observed_shas)
        exit_code = evidence.exit_code
        evidence_source = evidence.source
    return GateReceipt(
        schema_version=RECEIPT_SCHEMA_VERSION,
        from_phase=result.from_phase,
        to_phase=result.to_phase,
        verdict=result.verdict.value,
        gate_kind=gate_kind,
        reason=result.reason,
        gate_version=result.gate_version,
        target=target,
        manifest_source_kind=manifest_source_kind,
        mandated_node_ids=mandated,
        matched_node_ids=matched,
        sha256_pinned=pinned,
        sha256_observed=observed,
        pytest_exit_code=exit_code,
        evidence_source=evidence_source,
        runner=runner_kind(env),
        timestamp_utc=now.astimezone(timezone.utc).isoformat(),
        python_version=platform.python_version(),
        apt_engine_version=_engine_version(),
        error=error,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _engine_version() -> str:
    """apt-engine version, resolved lazily to avoid an import cycle with the package."""
    try:
        from . import __version__

        return __version__
    except Exception:  # pragma: no cover - defensive; __version__ is a literal
        return "unknown"
