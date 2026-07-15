"""Deterministic replay verification of a stored `GateReceipt`.

`receipt.py` produces a replay-checkable record of a measured gate run; this module
is the checker the receipt docstring promised (`apt-engine verify --replay`). It
re-derives the gate decision from the receipt's OWN recorded inputs and the current
checkout, WITHOUT re-running pytest, and reports whether the receipt still
reproduces:

  1. structural validation  — the JSON is a well-formed v1 receipt (schema_version
     match + required fields present and typed). A malformed/unknown receipt is
     refused, never silently trusted.
  2. sha256 re-check         — every mandated test file the receipt recorded a sha
     for is re-hashed from the checkout and compared to the recorded value; a
     drifted or missing file is a mismatch.
  3. audit_key recomputation — the receipt is rebuilt with the RE-DERIVED verdict
     and the RE-OBSERVED shas, and its `audit_key()` fingerprint is compared to the
     stored receipt's. Equal iff the checkout + verdict algebra reproduce it.
  4. verdict consistency     — the stored verdict is checked against the SET of
     verdicts the receipt's recorded measured inputs can actually produce via the
     pure `gate.evaluate_transition` (from the recorded pytest exit code + error +
     phase adjacency). A stored verdict OUTSIDE that set is a mismatch — e.g.
     exit-0-but-FAIL, exit-nonzero-but-PASS/CONDITIONAL, an ERROR verdict with no
     recorded error (or vice versa), or a non-adjacent / self-application transition
     that is not FAIL. pytest is NOT re-run.

     SCOPED GUARANTEE (this is NOT a total verdict check): the skip / conditional
     CALLER flags are NOT recorded on a v1 receipt, so PASS vs SKIP vs CONDITIONAL
     at the SAME exit code — and FAIL vs SKIP at a nonzero one — are genuinely
     indistinguishable from the recorded inputs. A tamper that only swaps among
     those flag-explained verdicts at a fixed exit code is therefore NOT caught
     here; the reliable verdict guarantee is the FAIL<->PASS (exit-code-pinned)
     inconsistency, plus the phase-structural and ERROR/error cross-checks above.

FAIL-CLOSED: every I/O or structural failure mode — an unreadable file, invalid
JSON, a non-object body, a missing OR mistyped field (including a non-string
`target`), an unsupported schema version, an unknown phase — yields
`replay_verified=False` with a typed `Mismatch`, never an exception out of the
public entry points. Terminal states are typed (`MismatchKind` enum), never a bare
exception. This is NOT a blanket "no false negative": the verdict check is scoped
(see 4) and the sha check is content-pin-only (see the TRUST BOUNDARY note) — a
receipt whose recorded inputs were themselves forged consistently is out of scope.

TRUST BOUNDARY (mirrors receipt.py / precondition.py): replay verifies internal
consistency + on-disk content pins; it does NOT re-execute the tests, so a receipt
whose RECORDED pytest exit code was itself forged cannot be caught here. The sound
guarantee is still a trusted CI runner + a non-caller manifest (ADR-0003), exactly
as for the receipt it replays.

Stdlib only — no runtime deps (belongs to the KG-free core).

# KG: rf-prom16-apt-gatereceipt-emitter (verify --replay is the receipt's promised
#     consumer), apt-engine ADR-0003 (trust boundary), lesson-prom16-apt-engine-hardening-2026-07-13
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .gate import Verdict, evaluate_transition
from .receipt import RECEIPT_SCHEMA_VERSION, GateReceipt

__all__ = [
    "MismatchKind",
    "Mismatch",
    "ReplayResult",
    "verify_replay",
    "verify_replay_file",
]


class MismatchKind(str, Enum):
    """Typed reason codes for why a receipt failed to replay (fail-closed)."""

    UNREADABLE_RECEIPT = "unreadable_receipt"          # file/JSON could not be read/parsed
    MALFORMED_RECEIPT = "malformed_receipt"            # missing/mistyped required field
    UNSUPPORTED_SCHEMA = "unsupported_schema_version"  # not this verifier's receipt schema
    MISSING_TEST_FILE = "missing_test_file"            # a recorded mandated file is absent
    SHA256_DRIFT = "sha256_drift"                      # on-disk sha != recorded sha
    VERDICT_INCONSISTENT = "verdict_inconsistent"      # recomputed verdict != stored verdict
    AUDIT_KEY_MISMATCH = "audit_key_mismatch"          # recomputed fingerprint != stored


@dataclass(frozen=True)
class Mismatch:
    kind: MismatchKind
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "detail": self.detail}


@dataclass(frozen=True)
class ReplayResult:
    """Typed outcome of a replay check. `replay_verified` iff `mismatches` is empty."""

    replay_verified: bool
    receipt_path: str
    checkout: str | None
    schema_version: str | None
    transition: str | None
    stored_verdict: str | None
    recomputed_verdict: str | None
    stored_audit_key: str | None
    recomputed_audit_key: str | None
    mismatches: tuple[Mismatch, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "replay_verified": self.replay_verified,
            "receipt_path": self.receipt_path,
            "checkout": self.checkout,
            "schema_version": self.schema_version,
            "transition": self.transition,
            "stored_verdict": self.stored_verdict,
            "recomputed_verdict": self.recomputed_verdict,
            "stored_audit_key": self.stored_audit_key,
            "recomputed_audit_key": self.recomputed_audit_key,
            "mismatches": [m.to_dict() for m in self.mismatches],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


#: Required receipt fields (name -> accepted python types) for structural validation.
_REQUIRED_FIELDS: dict[str, tuple[type, ...]] = {
    "schema_version": (str,),
    "from_phase": (str,),
    "to_phase": (str,),
    "verdict": (str,),
    "gate_kind": (str,),
    "mandated_node_ids": (list,),
    "matched_node_ids": (list,),
    "sha256_pinned": (dict,),
    "sha256_observed": (dict,),
    "pytest_exit_code": (int, type(None)),
    "error": (str, type(None)),
}

#: Optional receipt fields that flow into a real operation (not just display) and so
#: must be type-checked WHEN PRESENT — even though they may be legitimately absent.
#: `target` is joined into a filesystem `Path` (`_base_dir`); a non-string value
#: (JSON number / array / object) would raise `TypeError` there, so it is rejected
#: as a MALFORMED_RECEIPT during structural validation rather than crashing the
#: verifier (fail-closed). Absence is fine (defaults to None -> current directory).
_OPTIONAL_TYPED_FIELDS: dict[str, tuple[type, ...]] = {
    "target": (str, type(None)),
}


def verify_replay_file(receipt_path: str, *, checkout: str | None = None) -> ReplayResult:
    """Load a receipt JSON from `receipt_path` and replay-verify it (fail-closed)."""
    try:
        raw = Path(receipt_path).read_text()
    except OSError as exc:
        return _fatal(receipt_path, checkout, MismatchKind.UNREADABLE_RECEIPT,
                      f"cannot read receipt: {exc}")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return _fatal(receipt_path, checkout, MismatchKind.UNREADABLE_RECEIPT,
                      f"invalid receipt JSON: {exc}")
    if not isinstance(data, dict):
        return _fatal(receipt_path, checkout, MismatchKind.MALFORMED_RECEIPT,
                      "receipt is not a JSON object")
    return verify_replay(data, receipt_path=receipt_path, checkout=checkout)


def verify_replay(
    data: dict[str, Any],
    *,
    receipt_path: str = "<in-memory>",
    checkout: str | None = None,
) -> ReplayResult:
    """Replay-verify a receipt already parsed into a dict (fail-closed)."""
    struct = _structural_mismatches(data)
    if struct:
        # Cannot reason about a malformed/unknown-schema receipt: refuse.
        return _fatal_multi(receipt_path, checkout,
                            str(data.get("schema_version")) if isinstance(
                                data.get("schema_version"), str) else None,
                            struct)

    receipt = _receipt_from_dict(data)
    mismatches: list[Mismatch] = []

    # (2) sha256 re-check + (3) re-observe for the recomputed fingerprint.
    base = _base_dir(checkout, receipt.target)
    re_observed, sha_mismatches = _recheck_shas(receipt, base)
    mismatches.extend(sha_mismatches)

    # (4) verdict consistency: is the stored verdict one the RECORDED measured inputs
    # can actually produce? (No pytest.) The skip/conditional caller flags are not on
    # the receipt, so PASS/SKIP/CONDITIONAL at a fixed exit code are indistinguishable
    # — see the module docstring's SCOPED GUARANTEE. `consistent is None` means the
    # verdict is not re-derivable (asserted receipt: no measured inputs) -> not checked.
    consistent = _consistent_verdicts(receipt)
    recomputed_verdict = _representative_verdict(receipt, consistent)
    if consistent is not None and receipt.verdict not in consistent:
        mismatches.append(Mismatch(
            MismatchKind.VERDICT_INCONSISTENT,
            f"stored verdict {receipt.verdict!r} is not producible from the recorded "
            f"inputs (exit_code={receipt.pytest_exit_code!r}, "
            f"error_present={receipt.error is not None}); consistent verdicts: "
            f"{sorted(consistent)}",
        ))

    # (3) audit_key recomputation: rebuild with the re-derived verdict + re-observed
    # shas and compare the fingerprint to the stored receipt's.
    stored_key = _audit_key_hex(receipt)
    recomputed = _rebuild_receipt(receipt, recomputed_verdict, re_observed)
    recomputed_key = _audit_key_hex(recomputed)
    if recomputed_key != stored_key:
        mismatches.append(Mismatch(
            MismatchKind.AUDIT_KEY_MISMATCH,
            f"recomputed audit_key {recomputed_key} != stored {stored_key}",
        ))

    return ReplayResult(
        replay_verified=not mismatches,
        receipt_path=receipt_path,
        checkout=checkout,
        schema_version=receipt.schema_version,
        transition=f"{receipt.from_phase}->{receipt.to_phase}",
        stored_verdict=receipt.verdict,
        recomputed_verdict=recomputed_verdict.value if recomputed_verdict else None,
        stored_audit_key=stored_key,
        recomputed_audit_key=recomputed_key,
        mismatches=tuple(mismatches),
    )


# --------------------------------------------------------------------------- #
#  internals                                                                    #
# --------------------------------------------------------------------------- #


def _structural_mismatches(data: dict[str, Any]) -> list[Mismatch]:
    """Required-field presence/type + schema-version check. Empty => structurally OK."""
    out: list[Mismatch] = []
    sv = data.get("schema_version")
    if sv != RECEIPT_SCHEMA_VERSION:
        out.append(Mismatch(
            MismatchKind.UNSUPPORTED_SCHEMA,
            f"schema_version {sv!r} != supported {RECEIPT_SCHEMA_VERSION!r}",
        ))
    for name, types in _REQUIRED_FIELDS.items():
        if name not in data:
            out.append(Mismatch(MismatchKind.MALFORMED_RECEIPT, f"missing field {name!r}"))
        elif not isinstance(data[name], types):
            # bool is an int subclass — reject it for the int-typed exit code so a
            # `true` can't masquerade as an exit code.
            out.append(Mismatch(
                MismatchKind.MALFORMED_RECEIPT,
                f"field {name!r} has wrong type {type(data[name]).__name__}",
            ))
        elif name == "pytest_exit_code" and isinstance(data[name], bool):
            out.append(Mismatch(
                MismatchKind.MALFORMED_RECEIPT, "field 'pytest_exit_code' is a bool, not an int",
            ))
    # Optional-but-typed fields: absence is fine, but a present value that would
    # crash a downstream operation (e.g. a non-string `target` fed to Path()) is a
    # fail-closed MALFORMED_RECEIPT, not an unhandled exception.
    for name, types in _OPTIONAL_TYPED_FIELDS.items():
        if name in data and not isinstance(data[name], types):
            out.append(Mismatch(
                MismatchKind.MALFORMED_RECEIPT,
                f"field {name!r} has wrong type {type(data[name]).__name__}",
            ))
    return out


def _receipt_from_dict(data: dict[str, Any]) -> GateReceipt:
    """Rebuild a `GateReceipt` from a structurally-validated dict (lists -> tuples)."""
    return GateReceipt(
        schema_version=data["schema_version"],
        from_phase=data["from_phase"],
        to_phase=data["to_phase"],
        verdict=data["verdict"],
        gate_kind=data["gate_kind"],
        reason=str(data.get("reason", "")),
        gate_version=data.get("gate_version"),
        target=data.get("target"),
        manifest_source_kind=str(data.get("manifest_source_kind", "")),
        mandated_node_ids=tuple(data["mandated_node_ids"]),
        matched_node_ids=tuple(data["matched_node_ids"]),
        sha256_pinned=dict(data["sha256_pinned"]),
        sha256_observed=dict(data["sha256_observed"]),
        pytest_exit_code=data["pytest_exit_code"],
        evidence_source=data.get("evidence_source"),
        runner=str(data.get("runner", "")),
        timestamp_utc=str(data.get("timestamp_utc", "")),
        python_version=str(data.get("python_version", "")),
        apt_engine_version=str(data.get("apt_engine_version", "")),
        error=data.get("error"),
    )


def _base_dir(checkout: str | None, target: str | None) -> Path:
    """Directory the mandated node-id file parts resolve against.

    `--checkout` overrides; else the receipt's recorded `target` (the dir passed to
    `--measure`); else the current directory. Mirrors the gate's own
    `base = Path(target).resolve()` node-id resolution.
    """
    return Path(checkout if checkout is not None else (target or "."))


def _file_of_node_id(node_id: str) -> str:
    """The file-path portion of a pytest node id (before `::`)."""
    return node_id.partition("::")[0]


def _recheck_shas(receipt: GateReceipt, base: Path) -> tuple[dict[str, str], list[Mismatch]]:
    """Re-hash each recorded mandated file; compare to the recorded sha.

    Returns `(re_observed, mismatches)` where `re_observed` keys the freshly hashed
    shas by declared node id (same keying as the receipt), for the fingerprint
    recomputation. A missing file or a drifted sha is a fail-closed mismatch and is
    left OUT of `re_observed` (missing) / included with its drifted value (drift),
    so the recomputed audit_key also diverges.
    """
    re_observed: dict[str, str] = {}
    mismatches: list[Mismatch] = []
    # Only node ids the gate actually recorded a sha for are re-checkable (name-only
    # reqs never produced one). Sort for deterministic mismatch ordering.
    for node_id in sorted(receipt.sha256_observed):
        recorded = receipt.sha256_observed[node_id]
        file_path = base / _file_of_node_id(node_id)
        try:
            actual = hashlib.sha256(file_path.read_bytes()).hexdigest()
        except OSError:
            mismatches.append(Mismatch(
                MismatchKind.MISSING_TEST_FILE,
                f"{node_id}: mandated test file not readable at {file_path}",
            ))
            continue
        re_observed[node_id] = actual
        if actual != recorded:
            mismatches.append(Mismatch(
                MismatchKind.SHA256_DRIFT,
                f"{node_id}: recorded {recorded} but checkout has {actual}",
            ))
    return re_observed, mismatches


#: The three valid (conditional, skipped) flag combinations the caller could have
#: passed to `evaluate_transition`. `(True, True)` is rejected by the algebra
#: (mutually exclusive), so it is excluded — enumerating the rest yields every
#: verdict the RECORDED inputs leave open, since the flags themselves are not on the
#: receipt.
_FLAG_COMBOS: tuple[tuple[bool, bool], ...] = ((False, False), (True, False), (False, True))


def _consistent_verdicts(receipt: GateReceipt) -> frozenset[str] | None:
    """The set of verdict values the receipt's RECORDED inputs can actually produce.

    No pytest is run. The precondition truth is read off the RECORDED exit code
    (`met == exit_code == 0`); an `error` field means a could-not-evaluate ERROR
    (the pure algebra never yields ERROR, so error-present <=> {ERROR}). Otherwise
    every un-recorded skip/conditional caller flag is enumerated so the returned set
    is exactly what a faithful receipt's stored verdict is allowed to be — no more
    (a stored verdict outside it is a tamper) and no less (PASS/SKIP/CONDITIONAL at
    one exit code all remain admissible, because the distinguishing flag is not on
    the receipt; see the module docstring's SCOPED GUARANTEE).

    Returns `None` for the `asserted` gate kind (no measured inputs to constrain the
    verdict). An unknown phase yields the EMPTY set, so any stored verdict is then
    flagged inconsistent — fail-closed, never swallowed.
    """
    if receipt.error is not None:
        return frozenset({Verdict.ERROR.value})
    if receipt.gate_kind == "asserted":
        return None  # no measured inputs recorded; nothing to constrain
    met = receipt.pytest_exit_code == 0
    out: set[str] = set()
    for conditional, skipped in _FLAG_COMBOS:
        try:
            result = evaluate_transition(
                receipt.from_phase,
                receipt.to_phase,
                precondition_met=met,
                conditional=conditional,
                skipped=skipped,
            )
        except (KeyError, ValueError):
            continue  # unknown phase for this combo -> contributes no verdict
        out.add(result.verdict.value)
    return frozenset(out)


def _representative_verdict(
    receipt: GateReceipt, consistent: frozenset[str] | None
) -> Verdict | None:
    """A single verdict to display + rebuild the fingerprint with (no pytest).

    When the stored verdict is admissible (in `consistent`), reuse it so the
    recomputed `audit_key` reflects only on-disk content drift. When it is NOT
    admissible (or the phase is unknown / no measured inputs), fall back to the
    baseline no-flags verdict (ERROR if an error was recorded), which necessarily
    differs from the inconsistent stored verdict so the fingerprint diverges too.
    Returns `None` for asserted receipts (verdict left as-stored for the rebuild).
    """
    if receipt.error is not None:
        return Verdict.ERROR
    if receipt.gate_kind == "asserted":
        return None
    if consistent is not None and receipt.verdict in consistent:
        return Verdict(receipt.verdict)
    try:
        return evaluate_transition(
            receipt.from_phase,
            receipt.to_phase,
            precondition_met=(receipt.pytest_exit_code == 0),
        ).verdict
    except (KeyError, ValueError):
        return Verdict.ERROR


def _rebuild_receipt(
    receipt: GateReceipt,
    recomputed_verdict: Verdict | None,
    re_observed: dict[str, str],
) -> GateReceipt:
    """A copy of `receipt` with the re-derived verdict + re-observed shas swapped in.

    Every other audit_key input (gate_kind, manifest_source_kind, mandated ids,
    sha256_pinned, pytest_exit_code, error) is taken as-recorded, so the recomputed
    fingerprint diverges from the stored one exactly when the verdict or the on-disk
    content changed.
    """
    from dataclasses import replace

    verdict = recomputed_verdict.value if recomputed_verdict is not None else receipt.verdict
    return replace(receipt, verdict=verdict, sha256_observed=re_observed)


def _audit_key_hex(receipt: GateReceipt) -> str:
    """Stable hex digest of a receipt's `audit_key()` (deterministic serialisation)."""
    return hashlib.sha256(
        json.dumps(_jsonable(receipt.audit_key()), sort_keys=True).encode()
    ).hexdigest()


def _jsonable(value: Any) -> Any:
    """Recursively turn an audit_key tuple (nested tuples) into JSON-serialisable lists."""
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _fatal(
    receipt_path: str, checkout: str | None, kind: MismatchKind, detail: str
) -> ReplayResult:
    return _fatal_multi(receipt_path, checkout, None, [Mismatch(kind, detail)])


def _fatal_multi(
    receipt_path: str,
    checkout: str | None,
    schema_version: str | None,
    mismatches: list[Mismatch],
) -> ReplayResult:
    return ReplayResult(
        replay_verified=False,
        receipt_path=receipt_path,
        checkout=checkout,
        schema_version=schema_version,
        transition=None,
        stored_verdict=None,
        recomputed_verdict=None,
        stored_audit_key=None,
        recomputed_audit_key=None,
        mismatches=tuple(mismatches),
    )
