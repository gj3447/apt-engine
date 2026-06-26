from apt_engine.gate import Verdict, can_advance, evaluate_transition


def test_skip_is_never_pass():
    # Load-bearing rule from the gate-semantics ADR (taliban-blocker-C9-01 fix).
    assert can_advance(Verdict.SKIP) is False
    assert can_advance(Verdict.PASS) is True
    assert can_advance(Verdict.FAIL) is False
    assert can_advance(Verdict.CONDITIONAL) is False


def test_happy_path_pass_unlocks_downstream():
    r = evaluate_transition("SA", "SP", precondition_met=True)
    assert r.verdict is Verdict.PASS
    assert r.verdict.unlocks_downstream is True
    assert r.gate_version is None


def test_precondition_unmet_fails_with_canonical_gate_version():
    r = evaluate_transition("ST", "SCW", precondition_met=False)
    assert r.verdict is Verdict.FAIL
    assert r.gate_version == "v27_phase_scw_dispatch_guard"


def test_non_adjacent_transition_fails():
    r = evaluate_transition("SA", "SCW", precondition_met=True)
    assert r.verdict is Verdict.FAIL
    assert "non-adjacent" in r.reason


def test_explicit_skip_yields_skip_not_pass():
    r = evaluate_transition("SP", "ST", precondition_met=True, skipped=True)
    assert r.verdict is Verdict.SKIP
    assert can_advance(r.verdict) is False


def test_conditional_requires_followup():
    r = evaluate_transition("SCW", "MetaReview", precondition_met=True, conditional=True)
    assert r.verdict is Verdict.CONDITIONAL
    assert can_advance(r.verdict) is False


def test_metareview_self_application_is_fail():
    r = evaluate_transition("MetaReview", "MetaReview", precondition_met=True)
    assert r.verdict is Verdict.FAIL
    assert "self_application_forbidden" in r.reason


def test_self_application_takes_precedence_over_precondition():
    # Even with preconditions met, a forbidden self-loop must fail.
    r = evaluate_transition("MetaReview", "MetaReview", precondition_met=True, conditional=False)
    assert r.verdict is Verdict.FAIL
