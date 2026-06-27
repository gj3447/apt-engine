"""(b) legion wiring — revert-proof invariants binding commanders to the gate.

The load-bearing claims (from the user's framing + legion_roster):
  - naesengmoon emits the verdict == gate.Verdict algebra.
  - hades realizes IFF the verdict is PASS (== can_advance); SKIP never realizes.
  - naesengmoon needs all four prior provides before it can emit a verdict.
"""

from apt_engine.gate import Verdict, can_advance
from apt_engine.legion import (
    COMMANDERS,
    KG_CANONICAL_NODE,
    ROSTER,
    commander,
    hades_realizes,
    naesengmoon_ready,
    realize_commander,
    verdict_commander,
)


def test_seven_commanders_in_canonical_order():
    assert ROSTER == (
        "prometheus",
        "longinus",
        "eureka",
        "occam",
        "naesengmoon",
        "hades",
        "jaebaeman",
    )
    assert len(COMMANDERS) == 7


def test_jaebaeman_is_dispatch_loop_not_a_stage():
    assert commander("jaebaeman").is_stage is False
    assert all(c.is_stage for c in COMMANDERS if c.name != "jaebaeman")


def test_naesengmoon_emits_the_verdict():
    nsm = verdict_commander()
    assert nsm.name == "naesengmoon"
    assert nsm.provides == ("verdict",)


def test_hades_realizes_iff_pass():
    # The whole point: 실현 only behind a PASS verdict.
    assert hades_realizes(Verdict.PASS) is True
    assert hades_realizes(Verdict.SKIP) is False
    assert hades_realizes(Verdict.FAIL) is False
    assert hades_realizes(Verdict.CONDITIONAL) is False
    # hades_realizes is definitionally can_advance.
    for v in Verdict:
        assert hades_realizes(v) == can_advance(v)


def test_hades_requires_the_verdict_provide():
    assert realize_commander().name == "hades"
    assert realize_commander().requires == ("verdict",)


def test_naesengmoon_needs_all_four_prior_provides():
    full = {"acquired", "bindings", "abstractions", "hygiene"}
    assert naesengmoon_ready(full) is True
    # Missing any one keeps the verdict locked.
    for missing in full:
        assert naesengmoon_ready(full - {missing}) is False


def test_every_commander_has_a_canonical_kg_node():
    assert set(KG_CANONICAL_NODE.keys()) == set(ROSTER)
    assert all(KG_CANONICAL_NODE[name] for name in ROSTER)
