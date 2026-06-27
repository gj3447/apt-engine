"""(b) The 7 legion commanders and how the gate algebra binds to them.

APT is the methodology that runs the **legion** (비행기맨 #4) — its 7 commanders
are the executors; `phases.py`/`gate.py` are *when* and *under what verdict* they
run. Canonical roster (bhgman_tool `legion_roster`):

    prometheus  획득 acquire   run_cypher          -> acquired
    longinus    연결 bind      run_cypher          -> bindings
    eureka      창조 create    run_cypher          -> abstractions
    occam       정리 hygiene   run_cypher          -> hygiene
    naesengmoon 검증 verify    acquired+bindings+abstractions+hygiene -> VERDICT
    hades       실현 realize   verdict             -> realized
    jaebaeman   출격 dispatch  (Legion.run loop itself, not a stage)

The load-bearing tie to this engine:
  - **naesengmoon emits the verdict** — exactly the `gate.Verdict` algebra
    (PASS / FAIL / SKIP / CONDITIONAL).
  - **hades realizes iff PASS** — `hades_realizes(v)` is `gate.can_advance(v)`.
    SKIP is never realize (SKIP != PASS), mirroring the gate-semantics ADR.
  - **naesengmoon requires all four prior provides** before it can emit a verdict
    (acquired+bindings+abstractions+hygiene), per the roster contract.

`tests/test_legion.py` pins these as revert-proof invariants.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .gate import Verdict, can_advance

__all__ = [
    "Commander",
    "COMMANDERS",
    "ROSTER",
    "commander",
    "verdict_commander",
    "realize_commander",
    "hades_realizes",
    "naesengmoon_ready",
    "KG_CANONICAL_NODE",
]


@dataclass(frozen=True)
class Commander:
    name: str
    verb_ko: str
    verb_en: str
    requires: tuple[str, ...]
    provides: tuple[str, ...]
    is_stage: bool = True  # jaebaeman is the dispatch loop, not a stage
    aliases: tuple[str, ...] = field(default_factory=tuple)


# Canonical order: 획득 → 연결 → 창조 → 정리 → 검증 → 실현 (+ 출격 dispatch loop).
COMMANDERS: tuple[Commander, ...] = (
    Commander("prometheus", "획득", "acquire", ("run_cypher",), ("acquired",)),
    Commander("longinus", "연결", "bind", ("run_cypher",), ("bindings",)),
    Commander("eureka", "창조", "create", ("run_cypher",), ("abstractions",)),
    Commander("occam", "정리", "hygiene", ("run_cypher",), ("hygiene",), aliases=("occam-kam",)),
    Commander(
        "naesengmoon",
        "검증",
        "verify",
        ("acquired", "bindings", "abstractions", "hygiene"),
        ("verdict",),
    ),
    Commander("hades", "실현", "realize", ("verdict",), ("realized",)),
    Commander("jaebaeman", "출격", "dispatch", (), (), is_stage=False),
)

ROSTER: tuple[str, ...] = tuple(c.name for c in COMMANDERS)

# Map each commander to its canonical LegionCommander node name in the consumer KG.
KG_CANONICAL_NODE: dict[str, str] = {
    "prometheus": "Prometheus",
    "longinus": "Longinus",
    "eureka": "eureka-canonical-2026-05-26",
    "occam": "occam-kam-canonical-2026-05-26",
    "naesengmoon": "naesengmoon-canonical-2026-06-26",
    "hades": "hades-canonical-2026-05-27",
    "jaebaeman": "JaebaeMan",
}

_BY_NAME: dict[str, Commander] = {}
for _c in COMMANDERS:
    _BY_NAME[_c.name] = _c
    for _a in _c.aliases:
        _BY_NAME[_a] = _c


def commander(name: str) -> Commander:
    try:
        return _BY_NAME[name.strip().lower()]
    except KeyError as exc:
        raise KeyError(f"unknown commander: {name!r}; valid: {ROSTER}") from exc


def verdict_commander() -> Commander:
    """The commander that emits the gate verdict — naesengmoon (검증)."""
    return _BY_NAME["naesengmoon"]


def realize_commander() -> Commander:
    """The commander that realizes a passed gate — hades (실현)."""
    return _BY_NAME["hades"]


def hades_realizes(verdict: Verdict) -> bool:
    """hades realizes iff the verdict unlocks downstream — identical to can_advance.

    This is the engine-level statement of "실현 only behind a PASS verdict":
    SKIP / FAIL / CONDITIONAL never realize.
    """
    return can_advance(verdict)


def naesengmoon_ready(provided: set[str]) -> bool:
    """naesengmoon can emit a verdict only once all four prior provides exist."""
    return set(verdict_commander().requires).issubset(provided)
