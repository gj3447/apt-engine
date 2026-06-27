"""On-disk APT phase detection.

Extracted and de-drifted from `bhgman_tool/engine/mcp_server/tools/apt.py`
(KG: span-mcp-tool-apt-phase-detect-2026-05-13). The skeleton hard-coded its own
phase tuple; this version imports the canonical `CHAIN` from `phases.py`, so the
detector and the contract can never disagree on order or membership.

Honest limitations (Goodhart safeguard, preserved from the skeleton):
  - File-based only. If a project tracks APT state in the KG with no on-disk
    artifact, the detector returns 'unknown' rather than fabricating a phase.
  - `confidence` is an evidence-source label (EXTRACTED / INFERRED / AMBIGUOUS),
    NOT a scalar score. Do not promote any single number as a quality metric.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .phases import CHAIN

__all__ = ["detect_phase", "PhaseReport"]

PhaseReport = dict[str, Any]

# Progression markers in apt-progress.md, keyed by canonical phase name.
_PHASE_PATTERNS: dict[str, re.Pattern[str]] = {
    "SA": re.compile(r"\bSA\s*(complete|bootstrap|EXTEND|in[_\s]progress)\b", re.IGNORECASE),
    "SP": re.compile(r"\bSP\s*(decomposition|in[_\s]progress|complete)\b", re.IGNORECASE),
    "ST": re.compile(r"\bST\s*(crystalliz|contract|in[_\s]progress|complete)\b", re.IGNORECASE),
    "SCW": re.compile(r"\bSCW\s*(implementation|TDD|in[_\s]progress|complete)\b", re.IGNORECASE),
    "MetaReview": re.compile(r"\bMeta[\s-]?Review\b", re.IGNORECASE),
    "Cleanup": re.compile(r"\b(Phase\s*6|Cleanup|ratchet)\b", re.IGNORECASE),
}

_NOTE_NO_ARTIFACTS = (
    "No apt-progress.md or feature-spans.json at repo root. The project may track "
    "APT state in KG only — call against a path that contains the on-disk artifact, "
    "or use KG-backed detection (not implemented in the stdlib core)."
)
_NOTE_DETECTION = (
    "File-based detection only; phase markers parsed from apt-progress.md via regex. "
    "confidence=EXTRACTED requires apt-progress.md present. No scalar score is "
    "reported — the boolean phase map and confidence tag are the canonical output."
)


def _validate_repo_path(repo_path: str) -> Path:
    p = Path(repo_path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"repo path not found: {repo_path}")
    if not p.is_dir():
        raise NotADirectoryError(f"not a directory: {repo_path}")
    return p


def _current_phase(detected: dict[str, bool]) -> str:
    """Latest phase with evidence, by canonical CHAIN order, else 'unknown'."""
    for name in reversed(CHAIN):
        if detected.get(name):
            return name
    return "unknown"


def _read_spans_file(spans_file: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(spans_file.read_text(errors="replace"))
    except json.JSONDecodeError:
        return []
    if not (isinstance(data, dict) and isinstance(data.get("spans"), list)):
        return []
    out: list[dict[str, Any]] = []
    for s in data["spans"]:
        if isinstance(s, dict) and isinstance(s.get("name"), str):
            out.append({"name": s["name"], "depth": s.get("depth"), "status": s.get("status")})
    return out


def _empty_report(root: Path) -> PhaseReport:
    return {
        "repo_path": str(root),
        "current_phase": "unknown",
        "phases_detected": {p: False for p in CHAIN},
        "evidence_sources": [],
        "confidence": "AMBIGUOUS",
        "note": _NOTE_NO_ARTIFACTS,
    }


def detect_phase(repo_path: str) -> PhaseReport:
    """Detect the current APT phase by reading on-disk artifacts.

    Never raises for 'unknown' — that is a valid, honest signal.
    """
    root = _validate_repo_path(repo_path)
    progress = root / "apt-progress.md"
    spans_file = root / "feature-spans.json"
    has_progress = progress.is_file()
    has_spans = spans_file.is_file()

    if not has_progress and not has_spans:
        return _empty_report(root)

    detected = {p: False for p in CHAIN}
    sources: list[str] = []
    spans_summary: list[dict[str, Any]] = []

    if has_progress:
        text = progress.read_text(errors="replace")
        for name, pat in _PHASE_PATTERNS.items():
            if pat.search(text):
                detected[name] = True
        sources.append(progress.name)

    if has_spans:
        spans_summary = _read_spans_file(spans_file)
        if spans_summary:
            sources.append(spans_file.name)

    phase = _current_phase(detected)
    confidence = (
        "AMBIGUOUS" if phase == "unknown" else ("EXTRACTED" if has_progress else "INFERRED")
    )
    return {
        "repo_path": str(root),
        "current_phase": phase,
        "phases_detected": detected,
        "evidence_sources": sources,
        "spans_summary": spans_summary,
        "confidence": confidence,
        "note": _NOTE_DETECTION,
    }
