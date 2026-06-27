"""Magic-number drift detection — the stdlib core of the APT config resolver.

Ported from `resolver_prototype/resolver.py::validate` + `cypher_kg_client.py`.
No KG, no jinja — pure functions over (template body, cfg dict), so the drift
rule is unit-testable without any service. (RFC A6.1: a bare inline magic number
that should be a `{{cfg.X}}` marker is drift.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "CORE_MAGIC_FIELDS",
    "MAGIC_NUMBERS",
    "CFG_MARKER_RE",
    "DriftReport",
    "find_markers",
    "check_drift",
]

# The 5 core magic fields externalized to the KG MethodologyConfig node.
CORE_MAGIC_FIELDS: tuple[str, ...] = (
    "vibe_coding_sweet_min",
    "vibe_coding_sweet_max",
    "lens_count_constitutional",
    "contract_default_fields",
    "st_decision_areas",
)

# Bare occurrences of these magic values are drift (should be markers).
MAGIC_NUMBERS: frozenset[str] = frozenset({"200", "500", "9", "7", "8"})

CFG_MARKER_RE = re.compile(r"\{\{\s*cfg\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_INLINE_NUMBER_RE = re.compile(r"(?<![\w./])(\d{2,4})(?![\w./])")
_PARENTHETICAL_HINT_RE = re.compile(r"\(\s*현재\s+\d+(?:[-~]\d+)?\s*\)")


@dataclass(frozen=True)
class DriftReport:
    markers_found: tuple[str, ...]
    missing_in_cfg: tuple[str, ...]
    bare_inline_numbers: tuple[tuple[int, str], ...]  # (line_no, number)
    orphan_cfg_fields: tuple[str, ...]

    @property
    def ok(self) -> bool:
        """Clean iff no marker is unbacked and no magic number is hardcoded."""
        return not (self.missing_in_cfg or self.bare_inline_numbers)


def find_markers(body: str) -> tuple[str, ...]:
    """Sorted unique `{{cfg.X}}` marker names referenced in the template body."""
    return tuple(sorted(set(CFG_MARKER_RE.findall(body))))


def check_drift(
    body: str,
    cfg: dict,
    core_fields: tuple[str, ...] = CORE_MAGIC_FIELDS,
) -> DriftReport:
    """Detect drift between a SKILL.md template body and the resolved cfg.

    - missing_in_cfg: markers referenced but absent from cfg (would fail to render).
    - bare_inline_numbers: hardcoded magic numbers outside parenthetical hints.
    - orphan_cfg_fields: core fields present in cfg but never referenced.
    """
    markers = find_markers(body)
    missing = tuple(m for m in markers if m not in cfg)

    bare: list[tuple[int, str]] = []
    for lineno, line in enumerate(body.splitlines(), start=1):
        cleaned = _PARENTHETICAL_HINT_RE.sub("", line)
        for m in _INLINE_NUMBER_RE.finditer(cleaned):
            if m.group(1) in MAGIC_NUMBERS:
                bare.append((lineno, m.group(1)))

    orphans = tuple(f for f in core_fields if f in cfg and f not in markers)

    return DriftReport(
        markers_found=markers,
        missing_in_cfg=missing,
        bare_inline_numbers=tuple(bare),
        orphan_cfg_fields=orphans,
    )
