"""APT mandated impact tests — the contract a `SCW->MetaReview` transition must
keep green. Run by the measured gate in CI (the trusted runner), pinned by the
committed apt-impact.json and routed for owner review by CODEOWNERS. Keep this file
STABLE (its sha is pinned).
"""

from apt_engine import CHAIN, Verdict, evaluate_transition


def test_chain_is_canonical():
    assert CHAIN == ("SA", "SP", "ST", "SCW", "MetaReview", "Cleanup")


def test_skip_never_advances():
    r = evaluate_transition("SP", "ST", precondition_met=True, skipped=True)
    assert r.verdict is Verdict.SKIP and not r.verdict.unlocks_downstream
