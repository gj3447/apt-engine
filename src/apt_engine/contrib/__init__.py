"""Layer-2 ports — NOT part of the deterministic stdlib core.

Five modules (`gate_policy`, `circuit_breaker`, `opa`, `gate_override`, `resolver`)
were ported from the dgx-only SYMPOSIUM prototypes (`gj3447/symposium`
`THEORY/APT/{gate_endpoint,resolver}_prototype`); `kg_manifest` was added later as
the optional KG-backed `ManifestSource`. All six stay outside the core public
surface (see `docs/ADR-0002`):

  * none is wired into `evaluate_transition` (no composition root), and
  * the gate-server / OPA / config-resolver runtime is the dgx/SYMPOSIUM layer's
    job, not the stdlib substrate's (`adr-apt-dgx-runtime-delegation-2026-05-25`).

Kept here for whoever builds the standalone gate-endpoint. Import from
`apt_engine.contrib`; do NOT re-promote these into `apt_engine.__all__`.
"""

from __future__ import annotations

from . import resolver
from .circuit_breaker import CircuitBreaker, InMemoryStore, State
from .gate_override import GateOverride, disclosure, make_override, override_allows
from .gate_policy import EnforcementMode, OutwardVerdict, enforce
from .kg_manifest import KgClient, KgManifestSource, http_kg_client, neo4j_kg_client
from .opa import HTTPOPAClient, OPADecision, OPAPolicy, StaticOPAPolicy

__all__ = [
    "resolver",
    "CircuitBreaker",
    "InMemoryStore",
    "State",
    "GateOverride",
    "disclosure",
    "make_override",
    "override_allows",
    "EnforcementMode",
    "OutwardVerdict",
    "enforce",
    "HTTPOPAClient",
    "OPADecision",
    "OPAPolicy",
    "StaticOPAPolicy",
    # KG-backed manifest source (non-caller trust root, ADR-0003/0004).
    "KgClient",
    "KgManifestSource",
    "neo4j_kg_client",
    "http_kg_client",
]
