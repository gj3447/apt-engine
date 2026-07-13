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
  - A phase counts as progressed only with an explicit STATUS word next to its
    name ("SCW ... in progress", "ST ... complete"); a bare mention or roadmap
    item ("SA bootstrap", "Future cleanup", a lone "Meta-Review") does NOT. This
    is the primary guard against the confidently-wrong failure a "methodology
    outline" doc on an untouched repo used to trigger (`current_phase=Cleanup` at
    EXTRACTED (highest) confidence). Two further guards refuse to fabricate a
    determinate phase: a forward leap over a gap in the prefix falls back to the
    furthest gap-free phase at AMBIGUOUS, and a saturated map (all phases, or both
    terminal phases, marked — indistinguishable from a finished project vs. a full
    listing) resolves to 'unknown' at AMBIGUOUS.
  - Residual honest limit: a doc that FALSELY writes a status on every phase
    ("SA complete … Cleanup complete") is indistinguishable, at the boolean level,
    from a genuinely finished project — the saturation guard maps both to
    'unknown'. Disambiguating a lie needs a richer signal (per-span status / KG).
  - 'INFERRED' is RESERVED for a future spans-based inference path and is not
    currently emitted — the phase is derived from apt-progress.md markers only,
    so spans-only repos resolve to 'unknown', not a fabricated INFERRED phase.

KG: prom16-apt-engine-hardening-2026-07-13 (finding C1/C3),
    lesson-apt-detect-status-required-marker-2026-07-13.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .phases import CHAIN

__all__ = ["detect_phase", "PhaseReport"]

PhaseReport = dict[str, Any]

# A phase counts as PROGRESSED only when a LINE whose SUBJECT is the phase name
# (at line start, after markdown list/heading/checkbox markers) also carries a
# STATUS word that is NOT negated. Root-cause fix (PROM16 C3 + adversarial review
# 2026-07-13): a bare mention or a mid-sentence token used to fabricate a phase —
# "SA bootstrap" (a roadmap item), a stray "Future cleanup", "CI ratchet passed",
# "the SP diagram is complete", "St. Louis rollout complete", or "SA not complete".
# Line-subject anchoring + a negation guard reject all of those while accepting
# genuine progress lines ("- SCW implementation in progress"). This also fixes the
# old dead `ST crystalliz\b` alternative (ST is matched by its status, not a
# descriptor) so "ST crystallization complete" is detected.

#: STATUS words that mark real progress/completion (a plain descriptor is NOT one).
_STATUS_RE = re.compile(
    r"\b(?:complete[d]?|done|in[\s_-]?progress|passed|underway|WIP)\b", re.IGNORECASE
)
#: NEGATION / future-tense words; if one precedes the status on the line, the
#: status is not asserted (a plan or a not-yet, not progress).
_NEGATION_RE = re.compile(
    r"\bnot\b|\bno\b|\bnever\b|n['’]t\b|\bpending\b|\btodo\b|\btbd\b|\bplanned\b"
    r"|\bwill\b|\bfuture\b|\blater\b|\bupcoming\b|\bscheduled\b",
    re.IGNORECASE,
)
#: Leading markdown list bullet / heading / checkbox / ordinal markers, stripped
#: so the phase name must be the SUBJECT of the line, not embedded mid-sentence.
_MARKER_PREFIX_RE = re.compile(r"^[\s>]*(?:(?:[-*+]|#{1,6}|\[[ xX]\]|\d+\.)\s+)*")
#: Phase name anchored at the subject. SA/SP/ST/SCW are CASE-SENSITIVE (uppercase)
#: so "St." (Saint/Street), "as", "asp", … cannot collide; the two-word phases are
#: case-insensitive.
_SUBJECT_RE: dict[str, re.Pattern[str]] = {
    "SA": re.compile(r"\bSA\b"),
    "SP": re.compile(r"\bSP\b"),
    "ST": re.compile(r"\bST\b"),
    "SCW": re.compile(r"\bSCW\b"),
    "MetaReview": re.compile(r"\bMeta[\s-]?Review\b", re.IGNORECASE),
    "Cleanup": re.compile(r"\b(?:Phase\s*6|Cleanup)\b", re.IGNORECASE),
}


def _detect_markers(text: str) -> dict[str, bool]:
    """Line-by-line phase detection: a line marks a phase iff the phase name is the
    line's subject AND a non-negated status word appears on it."""
    detected = {p: False for p in CHAIN}
    for raw in text.splitlines():
        status = _STATUS_RE.search(raw)
        if status is None:
            continue  # no status word -> a plan/descriptor line, not progress
        neg = _NEGATION_RE.search(raw)
        if neg is not None and neg.start() < status.start():
            continue  # the status is negated / future-qualified ("SA not complete")
        subject = _MARKER_PREFIX_RE.sub("", raw, count=1)
        for name, name_re in _SUBJECT_RE.items():
            if name_re.match(subject):  # phase name at the START of the subject
                detected[name] = True
    return detected

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
_NOTE_TOC = (
    "Every phase (or both terminal phases) is marked in apt-progress.md — a boolean "
    "marker map cannot tell genuine completion from a roadmap/outline that merely "
    "lists all phases. current_phase is 'unknown' (deliberately NOT fabricated) with "
    "AMBIGUOUS confidence; phases_detected still shows the raw markers found. Use a "
    "richer signal (per-span status or the KG) to disambiguate a listing from progress."
)
_NOTE_GAP = (
    "A later phase is marked but an earlier phase in its prefix is not (a gap / "
    "forward leap — e.g. SA then Cleanup with SP/ST/SCW absent). Genuine linear "
    "progress fills a gap-free prefix, so the leap is not trusted: current_phase is "
    "the furthest GAP-FREE phase from SA and confidence is downgraded to AMBIGUOUS. "
    "phases_detected still shows every raw marker found."
)

#: The final two phases. A marker map that lights BOTH of them (or the entire
#: chain) is the signature of a roadmap/outline listing every phase rather than a
#: record of genuine linear progress — see `_looks_like_table_of_contents`.
_TERMINAL_PHASES: tuple[str, ...] = ("MetaReview", "Cleanup")


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


def _looks_like_table_of_contents(detected: dict[str, bool]) -> bool:
    """True when the marker map is 'saturated' — every phase, or both terminal
    phases, is marked.

    Such a shape is indistinguishable from a roadmap/outline that lists every
    phase (or a genuinely finished project), so reporting the last-listed phase
    as the current one would be fabrication. Genuine mid-work leaves later phases
    (especially both MetaReview AND Cleanup) unmarked, so this fires on the
    listing shape without touching an ordinary in-progress prefix like {SA,SP,SCW}.
    """
    all_present = all(detected.get(p) for p in CHAIN)
    both_terminal = all(detected.get(p) for p in _TERMINAL_PHASES)
    return all_present or both_terminal


def _contiguous_prefix(detected: dict[str, bool]) -> tuple[str, bool]:
    """The furthest phase reachable as a GAP-FREE prefix from SA, and whether the
    ENTIRE detected set is exactly that prefix (no isolated later hit).

    Returns (furthest_contiguous_phase | 'unknown', is_contiguous). Genuine linear
    progress fills a gap-free prefix; a later hit sitting after a gap is a
    'forward leap' (a mention of a future phase) that must not be trusted as the
    current phase — the C(S) contiguity invariant (PROM16 finding C1).
    """
    furthest = "unknown"
    for name in CHAIN:  # walk the prefix until the first gap
        if detected.get(name):
            furthest = name
        else:
            break
    seen_gap = False
    is_contiguous = True
    for name in CHAIN:  # any hit AFTER a gap => non-contiguous (forward leap)
        if not detected.get(name):
            seen_gap = True
        elif seen_gap:
            is_contiguous = False
            break
    return furthest, is_contiguous


def _read_spans_file(spans_file: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(spans_file.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        # OSError covers a TOCTOU race (file removed/locked between is_file() and
        # read) — degrade to no-spans rather than crash (the detector never raises
        # for a soft failure; 'unknown' is the honest floor).
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
        "spans_summary": [],  # keep the key uniform across every return path
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
        try:
            text: str | None = progress.read_text(errors="replace")
        except OSError:
            text = None  # raced/unreadable between is_file() and read -> degrade
        if text is not None:
            detected = _detect_markers(text)
            sources.append(progress.name)

    if has_spans:
        spans_summary = _read_spans_file(spans_file)
        if spans_summary:
            sources.append(spans_file.name)

    phase = _current_phase(detected)
    note = _NOTE_DETECTION
    if phase == "unknown":
        confidence = "AMBIGUOUS"
    elif _looks_like_table_of_contents(detected):
        # Saturated marker map: indistinguishable from a roadmap that lists every
        # phase. Refuse to fabricate — fall back to the honest 'unknown' while
        # keeping the raw markers visible in phases_detected (PROM16 C3 fix).
        phase, confidence, note = "unknown", "AMBIGUOUS", _NOTE_TOC
    else:
        contiguous_phase, is_contiguous = _contiguous_prefix(detected)
        if not is_contiguous:
            # Forward leap: a later phase is marked over a gap in its prefix. Don't
            # trust the leap — report the furthest gap-free phase and downgrade to
            # AMBIGUOUS (C(S) contiguity invariant, PROM16 finding C1).
            phase, confidence, note = contiguous_phase, "AMBIGUOUS", _NOTE_GAP
        else:
            # gap-free prefix => apt-progress.md present + a coherent run of markers.
            confidence = "EXTRACTED"
    return {
        "repo_path": str(root),
        "current_phase": phase,
        "phases_detected": detected,
        "evidence_sources": sources,
        "spans_summary": spans_summary,
        "confidence": confidence,
        "note": note,
    }
