"""APT pre-prompt config resolver (ported from SYMPOSIUM THEORY/APT/resolver_prototype).

The methodology's "magic numbers" (context budget, vibe-coding line band, lens
count, contract field count, ST decision-area count) live as a canonical KG node
`MethodologyConfig_default_v27`; SKILL.md templates reference them as `{{cfg.X}}`
markers. This package renders those markers and detects *drift* — a hardcoded
magic number that should have been a marker.

Layering (apt-engine philosophy — stdlib core, optional I/O):
  - `drift`         : STDLIB. marker extraction + drift detection (the epistemic core).
  - `config_source` : ConfigSource Protocol + stdlib DictConfigSource + lazy neo4j.
  - `render`        : lazy jinja2 rendering.

Install the I/O deps with:  pip install -e '.[resolver]'
"""

from __future__ import annotations

from .config_source import ConfigSource, DictConfigSource, verify_core_present
from .drift import CORE_MAGIC_FIELDS, DriftReport, check_drift, find_markers

__all__ = [
    "CORE_MAGIC_FIELDS",
    "DriftReport",
    "check_drift",
    "find_markers",
    "ConfigSource",
    "DictConfigSource",
    "verify_core_present",
]
